"""
Read-only analytics endpoints over topic grades.

Sibling modules cover the other two sources of numbers, on the same
`analytics/` prefix and with the same payload conventions:
analytics_subject.py for SubjectGrade (assignment marks) and
analytics_attendance.py for ScheduleAttendance. Shared helpers live in
analytics_common.py.

Three shapes of the same underlying data — TopicGrade → Topic → Lesson —
aggregated for charting rather than for editing:

- students/<id>/offerings/<id>/trajectory/  one student's grade per lesson in
                   one subject, with the class band around it. The "is this
                   student keeping up" line chart.
- offerings/<id>/topic-heatmap/             every student × every topic of one
                   offering. A dark column means reteach the topic, a dark row
                   means intervene with the student.
- students/<id>/subject-radar/              one student's standing across every
                   subject their class is taught, for one quarter.

Grading semantics — the whole module
------------------------------------
A missing TopicGrade counts as zero, matching Lesson.calculate_student_grade
and freeze_quarter_grades. Nothing is filtered out and no field is ever null:
an ungraded topic drags the average down exactly as a scored 0 would, and a
student with no rows at all reads 0.

Every response therefore carries a `coverage` figure next to the numbers —
how many topic grades were actually entered out of how many exist. It changes
no value; it is what lets a teacher tell a real zero from an unentered one,
and what makes a dip in the class band explainable as "not graded yet". For
trajectory and heatmap, coverage counts entered TopicGrade rows. For the
radar it counts lessons scoring above zero, which is how QuarterGradeSnapshot
already defines `graded_lesson_count` — the radar has to stay comparable with
the frozen snapshots it reads.

Read access:
- Trajectory and radar — can_access_student(): the student, their parents,
                   teachers who teach them, their homeroom teacher,
                   psychologists, and Admin / Principal / Supervisor.
- Heatmap        — teachers of the offering, the homeroom teacher of its class
                   group, psychologists, and admin roles. Students and parents
                   get 403: the payload is every classmate's scores, and a
                   one-row heatmap is not worth serving. Their equivalent is
                   the trajectory endpoint, which shows the class only as an
                   anonymous band.
Nothing here writes.
"""

from collections import defaultdict

from django.db.models import Count, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student
from apps.home.models import AcademicYear, Enrollment, SubjectOffering
from apps.lesson.models import Lesson, QuarterGradeSnapshot, Topic, TopicGrade
from core.error_messages import NO_PERMISSION
from core.permissions import can_access_student

# Shared with the subject-grade and attendance analytics; aliased to the
# private names this module has always used them under.
from apps.lesson.api.analytics_common import (  # noqa: F401
    OFFERING_SELECT_RELATED,
    bool_param as _bool_param,
    can_read_class_wide,
    choice_param as _choice_param,
    class_students,
    date_param as _date_param,
    int_param as _int_param,
    mean as _mean,
    offering_payload as _offering_payload,
    percentile as _percentile,
    percentile_rank as _percentile_rank,
    rank as _rank,
    student_is_enrolled_in,
    student_payload as _student_payload,
    trend_slope as _trend_slope,
)

from apps.lesson.api.serializers import (
    StudentSubjectRadarSerializer,
    StudentTrajectorySerializer,
    TopicHeatmapSerializer,
)


# How the missing-grade rule is reported back to the client, so a frontend
# never has to assume it.
GRADING_NOTE = {'missing_topics_as': 'zero'}

# group_by=topic yields one column per Topic row rather than per title, which
# on a full quarter runs to hundreds. Cut it off and say so in the payload.
MAX_HEATMAP_COLUMNS = 60

SUBTOPIC_SEPARATOR = ' › '


# ── Aggregation ──

def lesson_grade_matrix(lessons, students):
    """
    Weighted lesson grades for every (lesson, student) pair, in two queries.

    Returns (grades, coverage):
        grades[(lesson_id, student_id)]   -> float, the weighted lesson grade
        coverage[(lesson_id, student_id)] -> (entered_topics, total_topics)

    Same arithmetic as Lesson.calculate_grades_bulk — SUM(weight/100 * grade)
    over the lesson's parent topics — with the coverage counts carried along,
    which is the only reason this does not just call it. A topic with no
    TopicGrade row contributes nothing, i.e. zero.
    """
    lesson_ids = [lesson.id for lesson in lessons]
    student_ids = [student.id for student in students]
    if not lesson_ids or not student_ids:
        return {}, {}

    topics_by_lesson = defaultdict(list)
    topic_rows = Topic.objects.filter(
        lesson_id__in=lesson_ids, parent__isnull=True,
    ).values('id', 'lesson_id', 'weight')
    for row in topic_rows:
        topics_by_lesson[row['lesson_id']].append(row)

    entered = {}
    grade_rows = TopicGrade.objects.filter(
        topic__lesson_id__in=lesson_ids,
        topic__parent__isnull=True,
        student_id__in=student_ids,
    ).values_list('topic_id', 'student_id', 'grade')
    for topic_id, student_id, grade in grade_rows:
        entered[(topic_id, student_id)] = grade

    grades = {}
    coverage = {}
    for lesson_id in lesson_ids:
        lesson_topics = topics_by_lesson.get(lesson_id, ())
        for student_id in student_ids:
            total = 0.0
            graded = 0
            for topic in lesson_topics:
                value = entered.get((topic['id'], student_id))
                if value is None:
                    continue  # missing -> 0, contributes nothing
                graded += 1
                total += float(value) * (float(topic['weight']) / 100)
            grades[(lesson_id, student_id)] = round(total, 2)
            coverage[(lesson_id, student_id)] = (graded, len(lesson_topics))

    return grades, coverage


def _title_key(parent_title, title):
    """Column key for title grouping — subtopics namespaced under their parent."""
    if parent_title is None:
        return title
    return f'{parent_title}{SUBTOPIC_SEPARATOR}{title}'


def topic_grade_matrix(lessons, students, group_by='topic_title',
                       include_subtopics=False):
    """
    Per-topic averages for every student, for the heatmap.

    `group_by='topic_title'` folds every same-named topic in scope into one
    column — Topic's unique_together is (lesson, parent, title), so "Homework"
    recurs once per lesson and the fold is what turns twelve lesson columns
    into one competency column. `group_by='topic'` keeps one column per Topic
    row instead.

    Returns (columns, cells, truncated):
        columns -> ordered list of {key, label, parent, weight, lesson_count,
                                    topic_count}
        cells[(column_key, student_id)] -> (value, entered_count)
    """
    lesson_ids = [lesson.id for lesson in lessons]
    student_ids = [student.id for student in students]
    if not lesson_ids or not student_ids:
        return [], {}, False

    lesson_position = {lesson.id: index for index, lesson in enumerate(lessons)}

    topic_qs = Topic.objects.filter(lesson_id__in=lesson_ids)
    if not include_subtopics:
        topic_qs = topic_qs.filter(parent__isnull=True)
    topic_rows = topic_qs.values(
        'id', 'lesson_id', 'title', 'weight', 'order', 'parent__title',
    )

    columns = {}
    column_of_topic = {}
    for row in topic_rows:
        if group_by == 'topic':
            key = str(row['id'])
            label = row['title']
        else:
            key = _title_key(row['parent__title'], row['title'])
            label = key

        column_of_topic[row['id']] = key
        column = columns.get(key)
        if column is None:
            column = columns[key] = {
                'key': key,
                'label': label,
                'parent': row['parent__title'],
                'topic_ids': [],
                'lesson_ids': set(),
                'weight_total': 0.0,
                'order': row['order'],
                'lesson_position': lesson_position.get(row['lesson_id'], 0),
            }
        column['topic_ids'].append(row['id'])
        column['lesson_ids'].add(row['lesson_id'])
        column['weight_total'] += float(row['weight'])
        column['order'] = min(column['order'], row['order'])
        column['lesson_position'] = min(
            column['lesson_position'], lesson_position.get(row['lesson_id'], 0),
        )

    if group_by == 'topic':
        ordered = sorted(
            columns.values(),
            key=lambda c: (c['lesson_position'], c['order'], c['label']),
        )
    else:
        ordered = sorted(columns.values(), key=lambda c: (c['order'], c['label']))

    truncated = len(ordered) > MAX_HEATMAP_COLUMNS
    if truncated:
        ordered = ordered[:MAX_HEATMAP_COLUMNS]

    kept_topic_ids = [
        topic_id for column in ordered for topic_id in column['topic_ids']
    ]

    # One grouped query. Summing rather than averaging in the database is
    # deliberate: AVG would average only the rows that exist, and the divisor
    # has to be the full column size for a missing grade to read as zero.
    totals = defaultdict(lambda: [0.0, 0])
    if kept_topic_ids:
        if group_by == 'topic':
            aggregated = TopicGrade.objects.filter(
                topic_id__in=kept_topic_ids, student_id__in=student_ids,
            ).values('topic_id', 'student_id').annotate(
                total=Sum('grade'), entered=Count('id'),
            )
            for row in aggregated:
                bucket = totals[
                    (column_of_topic[row['topic_id']], row['student_id'])
                ]
                bucket[0] += float(row['total'] or 0)
                bucket[1] += row['entered']
        else:
            aggregated = TopicGrade.objects.filter(
                topic_id__in=kept_topic_ids, student_id__in=student_ids,
            ).values(
                'topic__title', 'topic__parent__title', 'student_id',
            ).annotate(total=Sum('grade'), entered=Count('id'))
            for row in aggregated:
                key = _title_key(row['topic__parent__title'], row['topic__title'])
                bucket = totals[(key, row['student_id'])]
                bucket[0] += float(row['total'] or 0)
                bucket[1] += row['entered']

    cells = {}
    for column in ordered:
        divisor = len(column['topic_ids'])
        for student_id in student_ids:
            total, entered = totals.get((column['key'], student_id), (0.0, 0))
            value = round(total / divisor, 2) if divisor else 0.0
            cells[(column['key'], student_id)] = (value, entered)

    payload_columns = [
        {
            'key': column['key'],
            'label': column['label'],
            'parent': column['parent'],
            'weight': round(column['weight_total'] / len(column['topic_ids']), 2),
            'lesson_count': len(column['lesson_ids']),
            'topic_count': len(column['topic_ids']),
        }
        for column in ordered
    ]
    return payload_columns, cells, truncated


# ── Lesson scoping ──

def _apply_lesson_filters(queryset, params):
    """Narrow lessons by quarter / unit / date range, and echo the filters back."""
    quarter = _int_param(params, 'quarter', 1, 4)
    unit = _int_param(params, 'unit', 1, 15)
    date_from = _date_param(params, 'date_from')
    date_to = _date_param(params, 'date_to')

    if quarter is not None:
        queryset = queryset.filter(quarter=quarter)
    if unit is not None:
        queryset = queryset.filter(unit=unit)
    if date_from is not None:
        queryset = queryset.filter(date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(date__lte=date_to)

    return queryset, {
        'quarter': quarter,
        'unit': unit,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
    }


# ── Filter parameters, for the schema ──

LESSON_FILTER_PARAMS = [
    OpenApiParameter('quarter', int, description='Quarter, 1–4. Default: all.'),
    OpenApiParameter('unit', int, description='Unit, 1–15. Default: all.'),
    OpenApiParameter(
        'date_from', OpenApiTypes.DATE, description='Earliest lesson date, inclusive.',
    ),
    OpenApiParameter(
        'date_to', OpenApiTypes.DATE, description='Latest lesson date, inclusive.',
    ),
]


class StudentTrajectoryAPIView(APIView):
    """
    GET analytics/students/<student_id>/offerings/<offering_id>/trajectory/

    One student's weighted grade for every lesson of one subject, in lesson
    order, with the class mean / median / quartile band around each point —
    the line-plus-band chart that answers "is this student keeping up".

    The band is aggregate only: no classmate is named or identifiable, which
    is what lets a student or a parent call this endpoint at all. Pass
    include_class_stats=false to skip it and read the student's own line.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentTrajectorySerializer,
        parameters=LESSON_FILTER_PARAMS + [
            OpenApiParameter(
                'include_class_stats', bool,
                description=(
                    'Include the class mean / median / quartile band. '
                    'Default true; false skips the class-wide scan.'
                ),
            ),
        ],
        description=(
            'Per-lesson grade trajectory for one student in one offering. '
            'Missing topic grades count as zero, so an ungraded lesson reads '
            '0.0 — the per-point `coverage` block is what distinguishes that '
            'from a genuine zero. 404 when the student is not actively '
            'enrolled in the offering.'
        ),
    )
    def get(self, request, student_id, offering_id):
        student = get_object_or_404(
            Student.objects.select_related('user'), pk=student_id,
        )
        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )

        offering = get_object_or_404(
            SubjectOffering.objects.select_related(*OFFERING_SELECT_RELATED),
            pk=offering_id,
        )
        # 404 rather than 403: a caller who may see the student should not be
        # able to enumerate the offerings they are *not* taught by probing.
        if not student_is_enrolled_in(student, offering):
            raise Http404('This student is not enrolled in that offering.')

        include_class_stats = _bool_param(
            request.query_params, 'include_class_stats', True,
        )
        lessons_qs, filters = _apply_lesson_filters(
            offering.lessons.all(), request.query_params,
        )
        lessons = list(lessons_qs.order_by('date', 'order', 'id'))

        cohort = class_students(offering) if include_class_stats else [student]
        grades, coverage = lesson_grade_matrix(lessons, cohort)

        points = []
        student_values = []
        entered_total = 0
        topics_total = 0

        for lesson in lessons:
            value = grades.get((lesson.id, student.id), 0.0)
            student_values.append(value)
            entered, topic_count = coverage.get((lesson.id, student.id), (0, 0))
            entered_total += entered
            topics_total += topic_count

            point = {
                'lesson_id': lesson.id,
                'title': lesson.title,
                'date': lesson.date.isoformat() if lesson.date else None,
                'order': lesson.order,
                'quarter': lesson.quarter,
                'unit': lesson.unit,
                'status': lesson.status,
                'student_grade': value,
                'coverage': {
                    'topic_count': topic_count,
                    'graded_topic_count': entered,
                },
            }

            if include_class_stats:
                class_values = [
                    grades.get((lesson.id, other.id), 0.0) for other in cohort
                ]
                ordered_values = sorted(class_values)
                point.update({
                    'class_mean': _mean(class_values),
                    'class_median': _percentile(ordered_values, 0.5),
                    'p25': _percentile(ordered_values, 0.25),
                    'p75': _percentile(ordered_values, 0.75),
                    'class_min': round(ordered_values[0], 2) if ordered_values else 0.0,
                    'class_max': round(ordered_values[-1], 2) if ordered_values else 0.0,
                    'class_size': len(cohort),
                    'rank': _rank(class_values, value),
                })

            points.append(point)

        summary = {
            'lesson_count': len(lessons),
            'student_mean': _mean(student_values),
            'class_mean': None,
            'delta': None,
            'trend_slope': _trend_slope(student_values),
            'coverage': {
                'topic_count': topics_total,
                'graded_topic_count': entered_total,
            },
        }
        if include_class_stats and lessons:
            class_means = [
                _mean([grades.get((lesson.id, other.id), 0.0) for other in cohort])
                for lesson in lessons
            ]
            summary['class_mean'] = _mean(class_means)
            summary['delta'] = round(
                summary['student_mean'] - summary['class_mean'], 2,
            )

        return Response({
            'student': _student_payload(student),
            'offering': _offering_payload(offering),
            'filters': filters,
            'grading': GRADING_NOTE,
            'points': points,
            'summary': summary,
        })


class OfferingTopicHeatmapAPIView(APIView):
    """
    GET analytics/offerings/<offering_id>/topic-heatmap/

    Every student of one offering against every topic, as a matrix rather than
    a list of cells — 30 students by 10 topics is 300 numbers this way and 300
    objects the other.

    `matrix[i][j]` is `students[i]` scored on `topics[j]`; `coverage[i][j]` is
    how many topic grades were actually entered behind that cell. Both are
    dense and never null.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=TopicHeatmapSerializer,
        parameters=LESSON_FILTER_PARAMS + [
            OpenApiParameter(
                'group_by', str,
                enum=['topic_title', 'topic'],
                description=(
                    'topic_title (default) folds same-named topics across '
                    'lessons into one competency column. topic keeps one '
                    'column per Topic row.'
                ),
            ),
            OpenApiParameter(
                'include_subtopics', bool,
                description=(
                    'Add subtopic columns, keyed "Parent › Subtopic". '
                    'Default false.'
                ),
            ),
        ],
        description=(
            'Student × topic matrix for one offering. Missing topic grades '
            'count as zero and the divisor is the full column size, so a '
            'topic a student was never graded on reads 0.0 with a coverage '
            'of 0. Teachers of the offering, its homeroom teacher, '
            'psychologists and admin roles only.'
        ),
    )
    def get(self, request, offering_id):
        offering = get_object_or_404(
            SubjectOffering.objects.select_related(*OFFERING_SELECT_RELATED),
            pk=offering_id,
        )
        if not can_read_class_wide(request.user, offering):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )

        group_by = _choice_param(
            request.query_params, 'group_by', {'topic_title', 'topic'}, 'topic_title',
        )
        include_subtopics = _bool_param(
            request.query_params, 'include_subtopics', False,
        )
        lessons_qs, filters = _apply_lesson_filters(
            offering.lessons.all(), request.query_params,
        )
        lessons = list(lessons_qs.order_by('date', 'order', 'id'))
        students = class_students(offering)

        columns, cells, truncated = topic_grade_matrix(
            lessons, students,
            group_by=group_by,
            include_subtopics=include_subtopics,
        )

        matrix = []
        coverage_matrix = []
        for student in students:
            row = []
            coverage_row = []
            for column in columns:
                value, entered = cells.get((column['key'], student.id), (0.0, 0))
                row.append(value)
                coverage_row.append(entered)
            matrix.append(row)
            coverage_matrix.append(coverage_row)

        row_means = [_mean(row) for row in matrix]
        column_means = [
            _mean([matrix[i][j] for i in range(len(students))])
            for j in range(len(columns))
        ]

        filters.update({
            'group_by': group_by,
            'include_subtopics': include_subtopics,
        })

        return Response({
            'offering': _offering_payload(offering),
            'filters': filters,
            'grading': GRADING_NOTE,
            'scale': {'min': 0, 'max': offering.max_points},
            'students': [_student_payload(student) for student in students],
            'topics': columns,
            'matrix': matrix,
            'coverage': coverage_matrix,
            'row_means': row_means,
            'column_means': column_means,
            'class_size': len(students),
            'lesson_count': len(lessons),
            'truncated': truncated,
        })


class StudentSubjectRadarAPIView(APIView):
    """
    GET analytics/students/<student_id>/subject-radar/

    One axis per subject the student's class is taught, for one quarter, with
    the class mean and the student's percentile on each — the profile chart
    for a report card.

    Axes are ordered by subject name, never by value: reordering by value
    makes the radar's shape meaningless between quarters.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentSubjectRadarSerializer,
        parameters=[
            OpenApiParameter(
                'academic_year', int,
                description='Academic year id. Default: the active year.',
            ),
            OpenApiParameter(
                'quarter', int,
                description=(
                    "Quarter, 1–4. Default: the year's current quarter, "
                    'else 1.'
                ),
            ),
            OpenApiParameter(
                'source', str,
                enum=['auto', 'snapshot', 'live'],
                description=(
                    'auto (default) reads a frozen QuarterGradeSnapshot where '
                    'the student has one and computes the rest live, '
                    'reporting which per axis. snapshot omits axes with no '
                    'frozen row; live always recomputes.'
                ),
            ),
            OpenApiParameter(
                'include_class_mean', bool,
                description='Include class mean and percentile. Default true.',
            ),
        ],
        description=(
            'Per-subject standing for one student in one quarter. Missing '
            'topic grades count as zero. A subject with no lessons in the '
            'quarter still gets an axis, at 0.0 with lesson_count 0, so the '
            "radar's vertex count stays stable across quarters — read "
            'lesson_count before reading value.'
        ),
    )
    def get(self, request, student_id):
        student = get_object_or_404(
            Student.objects.select_related('user'), pk=student_id,
        )
        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )

        source = _choice_param(
            request.query_params, 'source', {'auto', 'snapshot', 'live'}, 'auto',
        )
        include_class_mean = _bool_param(
            request.query_params, 'include_class_mean', True,
        )

        year_id = _int_param(request.query_params, 'academic_year', 1)
        if year_id is not None:
            academic_year = get_object_or_404(AcademicYear, pk=year_id)
        else:
            academic_year = AcademicYear.objects.filter(is_active=True).first()
        if academic_year is None:
            return Response(self._empty(student, None, None, source))

        quarter = _int_param(request.query_params, 'quarter', 1, 4)
        if quarter is None:
            quarter = academic_year.current_quarter or 1

        enrollment = Enrollment.objects.filter(
            student=student, academic_year=academic_year, status='active',
        ).select_related('class_group', 'class_group__grade_level').first()
        if enrollment is None:
            return Response(self._empty(student, academic_year, quarter, source))

        offerings = list(
            SubjectOffering.objects.filter(
                class_group=enrollment.class_group,
                academic_year=academic_year,
            ).select_related('subject').order_by('subject__name', 'id')
        )
        if not offerings:
            payload = self._empty(student, academic_year, quarter, source)
            payload['class_group'] = str(enrollment.class_group)
            return Response(payload)

        cohort = [
            other.student
            for other in Enrollment.objects.filter(
                class_group=enrollment.class_group,
                academic_year=academic_year,
                status='active',
            ).select_related('student')
        ]

        snapshots = self._snapshot_map(source, offerings, cohort, quarter, academic_year)
        live_offerings = [
            offering for offering in offerings
            if source == 'live' or (
                source == 'auto' and (offering.id, student.id) not in snapshots
            )
        ]
        live = self._live_map(live_offerings, cohort, quarter)

        axes = []
        for offering in offerings:
            axis = self._axis(
                offering, student, cohort, snapshots, live, source,
                include_class_mean,
            )
            if axis is not None:
                axes.append(axis)

        return Response({
            'student': _student_payload(student),
            'academic_year': {'id': academic_year.id, 'year': academic_year.year},
            'class_group': str(enrollment.class_group),
            'quarter': quarter,
            'grading': GRADING_NOTE,
            'axes': axes,
            'summary': self._summary(axes, include_class_mean),
        })

    # ── payload assembly ──

    @staticmethod
    def _empty(student, academic_year, quarter, source):
        return {
            'student': _student_payload(student),
            'academic_year': (
                {'id': academic_year.id, 'year': academic_year.year}
                if academic_year else None
            ),
            'class_group': None,
            'quarter': quarter,
            'grading': GRADING_NOTE,
            'axes': [],
            'summary': {
                'overall_mean': 0.0,
                'class_overall_mean': None,
                'strongest': None,
                'weakest': None,
                'axis_count': 0,
                'subject_count': 0,
                'sources': {'snapshot': 0, 'live': 0},
            },
        }

    @staticmethod
    def _snapshot_map(source, offerings, cohort, quarter, academic_year):
        """(offering_id, student_id) -> QuarterGradeSnapshot, empty when source=live."""
        if source == 'live':
            return {}
        return {
            (snapshot.offering_id, snapshot.student_id): snapshot
            for snapshot in QuarterGradeSnapshot.objects.filter(
                offering__in=offerings,
                student__in=cohort,
                quarter=quarter,
                academic_year=academic_year,
            )
        }

    @staticmethod
    def _live_map(offerings, cohort, quarter):
        """
        (offering_id, student_id) -> (quarter_mean, lesson_count, graded_lesson_count)

        The quarter mean is the mean of the zero-filled lesson grades, and
        graded_lesson_count counts lessons scoring above zero — both exactly
        as freeze_quarter_grades computes them, so a live axis and a frozen
        one can sit on the same radar.
        """
        if not offerings or not cohort:
            return {}

        lessons = list(
            Lesson.objects.filter(
                offering_id__in=[offering.id for offering in offerings],
                quarter=quarter,
            ).order_by('date', 'order', 'id')
        )
        grades, _ = lesson_grade_matrix(lessons, cohort)

        by_offering = defaultdict(list)
        for lesson in lessons:
            by_offering[lesson.offering_id].append(lesson)

        result = {}
        for offering in offerings:
            offering_lessons = by_offering.get(offering.id, [])
            for student in cohort:
                values = [
                    grades.get((lesson.id, student.id), 0.0)
                    for lesson in offering_lessons
                ]
                result[(offering.id, student.id)] = (
                    _mean(values),
                    len(offering_lessons),
                    sum(1 for value in values if value > 0),
                )
        return result

    @staticmethod
    def _axis(offering, student, cohort, snapshots, live, source, include_class_mean):
        snapshot = snapshots.get((offering.id, student.id))

        if snapshot is not None and source != 'live':
            value = round(float(snapshot.percentage), 2)
            lesson_count = snapshot.lesson_count
            graded_lesson_count = snapshot.graded_lesson_count
            letter_grade = snapshot.letter_grade
            axis_source = 'snapshot'
            class_values = [
                round(float(other.percentage), 2)
                for other in (
                    snapshots.get((offering.id, member.id)) for member in cohort
                )
                if other is not None
            ]
        elif source == 'snapshot':
            return None  # no frozen row for this student — omit the axis
        else:
            value, lesson_count, graded_lesson_count = live.get(
                (offering.id, student.id), (0.0, 0, 0),
            )
            letter_grade = None
            axis_source = 'live'
            class_values = [
                live.get((offering.id, member.id), (0.0, 0, 0))[0]
                for member in cohort
            ]

        axis = {
            'offering_id': offering.id,
            'subject_id': offering.subject_id,
            'subject': offering.subject.name,
            'language_group': offering.subject.language_group,
            'value': value,
            'source': axis_source,
            'lesson_count': lesson_count,
            'graded_lesson_count': graded_lesson_count,
        }
        if letter_grade:
            axis['letter_grade'] = letter_grade
        if include_class_mean:
            axis['class_mean'] = _mean(class_values)
            axis['percentile'] = _percentile_rank(class_values, value)
        return axis

    @staticmethod
    def _summary(axes, include_class_mean):
        """
        Aggregates over the axes that actually have lessons behind them.

        An axis with lesson_count 0 stays on the radar so the vertex count
        holds steady between quarters, but it means "this subject ran no
        lessons", not "the student scored zero". Averaging it in would drag
        overall_mean down and hand `weakest` to whichever subject simply has
        not started yet — so the summary skips those, and subject_count
        reports how many it actually used.
        """
        scored = [axis for axis in axes if axis['lesson_count'] > 0]

        sources = {'snapshot': 0, 'live': 0}
        for axis in axes:
            sources[axis['source']] += 1

        strongest = max(scored, key=lambda a: a['value']) if scored else None
        weakest = min(scored, key=lambda a: a['value']) if scored else None

        summary = {
            'overall_mean': _mean([axis['value'] for axis in scored]),
            'class_overall_mean': None,
            'strongest': (
                {'subject': strongest['subject'], 'value': strongest['value']}
                if strongest else None
            ),
            'weakest': (
                {'subject': weakest['subject'], 'value': weakest['value']}
                if weakest else None
            ),
            'axis_count': len(axes),
            'subject_count': len(scored),
            'sources': sources,
        }
        if include_class_mean and scored:
            summary['class_overall_mean'] = _mean(
                [axis['class_mean'] for axis in scored]
            )
        return summary
