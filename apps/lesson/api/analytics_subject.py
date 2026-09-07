"""
Read-only analytics endpoints over subject grades.

The same three shapes as the topic-grade analytics, over the other gradebook —
SubjectGrade → SubjectAssignment → SubjectOffering:

- students/<id>/offerings/<id>/assignment-trajectory/  one student's mark on
                   every assignment of one subject, with the class band around
                   it. The line chart of "how is this student doing on the
                   actual work".
- offerings/<id>/assignment-heatmap/          every student × every assignment
                   of one offering. A dark column means the whole class fell
                   over that piece of work; a dark row means one student did.
- students/<id>/assignment-summary/           one student's standing across
                   every subject their class is taught, split by category.

Grading semantics — the whole module
------------------------------------
Nothing like the topic-grade zero-fill rule applies here, and the difference is
in the model rather than in taste. `SubjectGrade.grade` is nullable, and a row
is created the moment a teacher opens the assignment: a null grade is work not
marked yet, not work scored zero. A student with no row at all is in exactly
the same position. So by default **ungraded work is left out of the averages**,
and `missing=zero` is offered for the teacher who wants "not handed in = 0".
Both are reported back in `grading.missing_grades_as`.

Marks are normalised to a **percent of each assignment's own `max_grade`**,
because that is the only way a 20-point quiz and a 100-point exam can share an
axis. Raw `grade` and `max_grade` travel alongside every point so the original
numbers are never lost. An assignment with `max_grade` 0 yields 0.0 rather than
a division error.

Every response carries `coverage` — how many marks were actually entered out of
how many were possible — which is what separates "the class did badly" from
"the class has not been marked".

Read access:
- Trajectory and summary — can_access_student(): the student, their parents,
                   teachers who teach them, their homeroom teacher,
                   psychologists, and Admin / Principal / Supervisor.
- Heatmap        — teachers of the offering only. Students, parents, admin
                   roles and homeroom-only teachers stay out of this grading
                   page endpoint; their equivalent is the trajectory endpoint,
                   where the class appears only as an anonymous band.
Nothing here writes.
"""

from collections import defaultdict

from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student, Teacher
from apps.home.models import (
    AcademicYear, Enrollment, HomeroomTeacherAssignment, SubjectAssignment,
    SubjectGrade, SubjectOffering, TeachingAssignment,
)
from core.error_messages import NO_PERMISSION
from core.permissions import can_access_student, is_admin_role, is_teacher_role

from apps.lesson.api.analytics_common import (
    ACADEMIC_YEAR_PARAM,
    DATE_RANGE_PARAMS,
    OFFERING_SELECT_RELATED,
    academic_year_payload,
    band,
    bool_param,
    choice_param,
    class_students,
    class_group_payload,
    date_param,
    enrolled_students,
    int_param,
    mean,
    offering_payload,
    percentile_rank,
    rank,
    ratio,
    student_is_enrolled_in,
    student_payload,
    require_quarter_window,
    trend_slope,
)
from apps.lesson.api.serializers import (
    AssignmentHeatmapSerializer,
    StudentAssignmentSummarySerializer,
    StudentAssignmentTrajectorySerializer,
)


CATEGORIES = [value for value, _label in SubjectAssignment.CATEGORY_CHOICES]

MISSING_CHOICES = {'exclude', 'zero'}

# group_by is not offered here — an assignment is already the column — but a
# busy offering can still run to hundreds of them over a year. Cut it off at
# the most recent ones and say so in the payload.
MAX_HEATMAP_COLUMNS = 60

ASSIGNMENT_SELECT_RELATED = ('offering', 'offering__subject')


# ── Scoring ──

def _percent(grade, max_grade):
    """One mark as a percent of its assignment's maximum."""
    if grade is None or not max_grade:
        return 0.0
    return round(100 * float(grade) / float(max_grade), 2)


def assignment_percent_matrix(assignments, students):
    """
    Percent scores for every (assignment, student) pair, in one query.

    Returns (percents, raw, grade_ids, comments):
        percents[(assignment_id, student_id)] -> float, or None when unmarked
        raw[(assignment_id, student_id)]      -> the SubjectGrade.grade as given,
                                                 or None
        grade_ids[(assignment_id, student_id)] -> SubjectGrade.id for existing rows
        comments[(assignment_id, student_id)]  -> SubjectGrade.comments or ''

    None means "no mark", never "zero" — see the module docstring. Callers turn
    it into a number, or leave it out, according to the `missing` parameter.
    """
    assignment_ids = [assignment.id for assignment in assignments]
    student_ids = [student.id for student in students]
    if not assignment_ids or not student_ids:
        return {}, {}

    max_grades = {
        assignment.id: assignment.max_grade for assignment in assignments
    }

    percents = {}
    raw = {}
    grade_ids = {}
    comments = {}
    rows = SubjectGrade.objects.filter(
        assignment_id__in=assignment_ids, student_id__in=student_ids,
    ).values_list('id', 'assignment_id', 'student_id', 'grade', 'comments')
    for grade_id, assignment_id, student_id, grade, comment in rows:
        key = (assignment_id, student_id)
        raw[key] = grade
        grade_ids[key] = grade_id
        comments[key] = comment or ''
        # A row with a null grade is a placeholder: it stays unmarked.
        percents[key] = (
            None if grade is None
            else _percent(grade, max_grades.get(assignment_id))
        )

    return percents, raw, grade_ids, comments


def can_grade_offering(user, offering):
    """Whether the caller teaches the offering and may edit its grades."""
    if not is_teacher_role(user):
        return False

    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return False

    return TeachingAssignment.objects.filter(
        offering=offering, teacher=teacher,
    ).exists()


def _teacher_payload(teacher):
    full_name = teacher.user.get_full_name().strip() or teacher.user.username
    return {
        'id': teacher.id,
        'user_id': teacher.user_id,
        'full_name': full_name,
        'username': teacher.user.username,
    }


def _requested_teacher(request):
    teacher_id = int_param(request.query_params, 'teacher', 1)
    current_teacher = Teacher.objects.filter(user=request.user).first()

    if teacher_id is None:
        if current_teacher is None:
            return None, Response(
                {'detail': 'teacher is required. Use a teacher profile id.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return current_teacher, None

    if not is_admin_role(request.user):
        if current_teacher is None or current_teacher.id != teacher_id:
            return None, Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )

    teacher = get_object_or_404(
        Teacher.objects.select_related('user'), pk=teacher_id,
    )
    return teacher, None


def _active_or_requested_academic_year(params):
    year_id = int_param(params, 'academic_year', 1)
    if year_id is not None:
        return get_object_or_404(AcademicYear, pk=year_id)
    return AcademicYear.objects.filter(is_active=True).first()


def _access_for(offering, taught_ids, homeroom_class_group_ids):
    taught = offering.id in taught_ids
    homeroom = offering.class_group_id in homeroom_class_group_ids
    if taught and homeroom:
        access = 'teaching_and_homeroom'
    elif taught:
        access = 'teaching'
    else:
        access = 'homeroom'
    return access, taught, homeroom


def _values_for(percents, keys, missing):
    """
    The list of numbers an average should be taken over.

    Under `missing=exclude` unmarked cells drop out entirely, which is why the
    divisor moves with the number of marks entered. Under `missing=zero` they
    come in as 0.0 and the divisor is the full column.
    """
    values = []
    for key in keys:
        value = percents.get(key)
        if value is None:
            if missing == 'zero':
                values.append(0.0)
            continue
        values.append(value)
    return values


def _coverage(percents, assignments, students):
    """(entered, possible) marks over an assignment × student block."""
    possible = len(assignments) * len(students)
    entered = sum(
        1
        for assignment in assignments
        for student in students
        if percents.get((assignment.id, student.id)) is not None
    )
    return {
        'possible_count': possible,
        'graded_count': entered,
        'graded_share': ratio(entered, possible),
    }


def _category_breakdown(assignments, percents, student, missing):
    """
    Per-category means for one student — lesson work, exams and finals apart.

    Category is the one axis subject assignments have and lessons do not, and
    it is usually the interesting one: a student who is fine on classwork and
    falls over in exams looks average until the two are separated.
    """
    by_category = {}
    for category in CATEGORIES:
        in_category = [a for a in assignments if a.category == category]
        keys = [(a.id, student.id) for a in in_category]
        values = _values_for(percents, keys, missing)
        graded = sum(1 for key in keys if percents.get(key) is not None)
        by_category[category] = {
            'assignment_count': len(in_category),
            'graded_count': graded,
            'value': mean(values),
        }
    return by_category


# ── Filters ──

def _apply_assignment_filters(queryset, params):
    """Narrow assignments by category / date range, and echo the filters back."""
    category = choice_param(params, 'category', set(CATEGORIES), None)
    date_from = date_param(params, 'date_from')
    date_to = date_param(params, 'date_to')

    if category is not None:
        queryset = queryset.filter(category=category)
    if date_from is not None:
        queryset = queryset.filter(date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(date__lte=date_to)

    return queryset, {
        'category': category,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
    }


def _assignment_payload(assignment):
    return {
        'id': assignment.id,
        'title': assignment.title,
        'category': assignment.category,
        'date': assignment.date.isoformat() if assignment.date else None,
        'max_grade': assignment.max_grade,
    }


CATEGORY_PARAM = OpenApiParameter(
    'category', str, enum=CATEGORIES,
    description='Assignment category: lesson, exam or final. Default: all.',
)

MISSING_PARAM = OpenApiParameter(
    'missing', str, enum=sorted(MISSING_CHOICES),
    description=(
        'How unmarked work counts. exclude (default) leaves it out of the '
        'averages; zero counts it as 0.'
    ),
)

ASSIGNMENT_FILTER_PARAMS = [CATEGORY_PARAM] + DATE_RANGE_PARAMS + [MISSING_PARAM]


class StudentAssignmentTrajectoryAPIView(APIView):
    """
    GET analytics/students/<student_id>/offerings/<offering_id>/assignment-trajectory/

    One student's percent score on every assignment of one subject, in date
    order, with the class mean / median / quartile band around each point.

    The band is aggregate only: no classmate is named or identifiable, which is
    what lets a student or a parent call this endpoint at all. Pass
    include_class_stats=false to skip it and read the student's own line.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentAssignmentTrajectorySerializer,
        parameters=ASSIGNMENT_FILTER_PARAMS + [
            OpenApiParameter(
                'include_class_stats', bool,
                description=(
                    'Include the class mean / median / quartile band. '
                    'Default true; false skips the class-wide scan.'
                ),
            ),
        ],
        description=(
            'Per-assignment score trajectory for one student in one offering, '
            'as a percent of each assignment\'s own max_grade. Unmarked work is '
            'left out of the averages by default — `graded` on each point and '
            '`coverage` on the summary say how much of the work has been '
            'marked. 404 when the student is not actively enrolled in the '
            'offering.'
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

        missing = choice_param(
            request.query_params, 'missing', MISSING_CHOICES, 'exclude',
        )
        include_class_stats = bool_param(
            request.query_params, 'include_class_stats', True,
        )
        assignments_qs, filters = _apply_assignment_filters(
            offering.assignments.all(), request.query_params,
        )
        assignments = list(assignments_qs.order_by('date', 'created_at', 'id'))
        filters['missing'] = missing

        cohort = class_students(offering) if include_class_stats else [student]
        percents, raw, _grade_ids, _comments = assignment_percent_matrix(
            assignments, cohort,
        )

        points = []
        for assignment in assignments:
            key = (assignment.id, student.id)
            value = percents.get(key)
            graded = value is not None

            point = _assignment_payload(assignment)
            point.update({
                'grade': raw.get(key),
                'percent': 0.0 if value is None else value,
                'graded': graded,
            })

            if include_class_stats:
                class_values = _values_for(
                    percents,
                    [(assignment.id, other.id) for other in cohort],
                    missing,
                )
                point.update(_class_block(class_values, cohort, value, missing))

            points.append(point)

        student_values = _values_for(
            percents, [(a.id, student.id) for a in assignments], missing,
        )
        summary = {
            'assignment_count': len(assignments),
            'graded_count': len(
                [a for a in assignments if percents.get((a.id, student.id)) is not None]
            ),
            'student_mean': mean(student_values),
            'class_mean': None,
            'delta': None,
            'trend_slope': trend_slope(student_values),
            'by_category': _category_breakdown(
                assignments, percents, student, missing,
            ),
            'coverage': _coverage(percents, assignments, [student]),
        }
        if include_class_stats and assignments:
            class_means = [
                mean(_values_for(
                    percents, [(a.id, other.id) for other in cohort], missing,
                ))
                for a in assignments
            ]
            summary['class_mean'] = mean(class_means)
            summary['delta'] = round(
                summary['student_mean'] - summary['class_mean'], 2,
            )

        return Response({
            'student': student_payload(student),
            'offering': offering_payload(offering),
            'filters': filters,
            'grading': _grading_note(missing),
            'points': points,
            'summary': summary,
        })


def _grading_note(missing):
    """How the module's rules are reported back, so a frontend never guesses."""
    return {
        'missing_grades_as': 'zero' if missing == 'zero' else 'excluded',
        'scale': 'percent_of_max_grade',
    }


def _class_block(class_values, cohort, value, missing):
    """The band drawn around one point, plus this student's place in it."""
    stats = band(class_values)
    return {
        'class_mean': stats['mean'],
        'class_median': stats['median'],
        'p25': stats['p25'],
        'p75': stats['p75'],
        'class_min': stats['min'],
        'class_max': stats['max'],
        'class_size': len(cohort),
        'graded_class_count': len(class_values) if missing == 'exclude' else None,
        # An unmarked student has no place in the ranking; 0 says so without
        # pretending they came last.
        'rank': rank(class_values, value) if value is not None else 0,
    }


class OfferingAssignmentHeatmapAPIView(APIView):
    """
    GET analytics/offerings/<offering_id>/assignment-heatmap/

    Every student of one offering against every assignment, as a matrix rather
    than a list of cells — 30 students by 12 assignments is 360 numbers this
    way and 360 objects the other.

    `matrix[i][j]` is `students[i]` on `assignments[j]`, as a percent;
    `graded[i][j]` says whether that cell holds a real mark. Under the default
    `missing=exclude` an unmarked cell reads 0.0 with `graded` false, and is
    left out of every mean — read `graded` before reading the number.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=AssignmentHeatmapSerializer,
        parameters=ASSIGNMENT_FILTER_PARAMS,
        description=(
            'Student × assignment matrix for one offering, scored as a percent '
            'of each assignment\'s own max_grade so that a 20-point quiz and a '
            '100-point exam share a scale. Newest assignments win when the '
            'column cap bites. Teachers assigned to the offering only.'
        ),
    )
    def get(self, request, offering_id):
        offering = get_object_or_404(
            SubjectOffering.objects.select_related(*OFFERING_SELECT_RELATED),
            pk=offering_id,
        )
        if not can_grade_offering(request.user, offering):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )

        missing = choice_param(
            request.query_params, 'missing', MISSING_CHOICES, 'exclude',
        )
        assignments_qs, filters = _apply_assignment_filters(
            offering.assignments.all(), request.query_params,
        )
        filters['missing'] = missing

        assignments = list(assignments_qs.order_by('date', 'created_at', 'id'))
        truncated = len(assignments) > MAX_HEATMAP_COLUMNS
        if truncated:
            # Keep the most recent ones: an overflowing offering is a long year,
            # and the recent work is what a teacher is looking at.
            assignments = assignments[-MAX_HEATMAP_COLUMNS:]

        students = class_students(offering)
        percents, raw, grade_ids, comments = assignment_percent_matrix(
            assignments, students,
        )

        matrix = []
        graded_matrix = []
        raw_matrix = []
        grade_id_matrix = []
        comment_matrix = []
        for student in students:
            row = []
            graded_row = []
            raw_row = []
            grade_id_row = []
            comment_row = []
            for assignment in assignments:
                key = (assignment.id, student.id)
                value = percents.get(key)
                row.append(0.0 if value is None else value)
                graded_row.append(value is not None)
                raw_row.append(raw.get(key))
                grade_id_row.append(grade_ids.get(key))
                comment_row.append(comments.get(key, ''))
            matrix.append(row)
            graded_matrix.append(graded_row)
            raw_matrix.append(raw_row)
            grade_id_matrix.append(grade_id_row)
            comment_matrix.append(comment_row)

        row_means = [
            mean(_values_for(
                percents, [(a.id, student.id) for a in assignments], missing,
            ))
            for student in students
        ]
        columns = []
        column_means = []
        for assignment in assignments:
            keys = [(assignment.id, student.id) for student in students]
            values = _values_for(percents, keys, missing)
            column_means.append(mean(values))
            column = _assignment_payload(assignment)
            column['graded_count'] = sum(
                1 for key in keys if percents.get(key) is not None
            )
            columns.append(column)

        return Response({
            'offering': offering_payload(offering),
            'filters': filters,
            'grading': _grading_note(missing),
            'scale': {'min': 0, 'max': 100},
            'students': [student_payload(student) for student in students],
            'assignments': columns,
            'matrix': matrix,
            'graded': graded_matrix,
            'raw_grades': raw_matrix,
            'grade_ids': grade_id_matrix,
            'comments': comment_matrix,
            'row_means': row_means,
            'column_means': column_means,
            'coverage': _coverage(percents, assignments, students),
            'class_size': len(students),
            'assignment_count': len(assignments),
            'truncated': truncated,
        })


class AssignmentAnalyticsOfferingListAPIView(APIView):
    """
    GET analytics/assignment-offerings/

    Offerings a teacher should see on the assignment analytics screen.

    This is intentionally narrower than the schedule teaching-assignment list
    for admin users: the assignment heatmap is teacher-owned, so a mixed
    Admin/Teacher account needs the teacher's own analytics scope, not the
    whole school's offerings.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                'teacher', int,
                description=(
                    'Teacher profile id. Optional for teacher accounts; admin '
                    'roles may use it to inspect a specific teacher.'
                ),
            ),
            OpenApiParameter(
                'academic_year', int,
                description=(
                    'Academic year id. Defaults to the active academic year.'
                ),
            ),
        ],
        description=(
            'Assignment analytics offering picker for one teacher. Includes '
            'offerings they teach and active subjects in their homeroom class. '
            '`can_heatmap` is true only for offerings the teacher directly '
            'teaches.'
        ),
    )
    def get(self, request):
        teacher, error = _requested_teacher(request)
        if error is not None:
            return error

        academic_year = _active_or_requested_academic_year(request.query_params)
        if academic_year is None:
            return Response({
                'teacher': _teacher_payload(teacher),
                'academic_year': None,
                'offerings': [],
                'count': 0,
            })

        taught_assignments = list(
            TeachingAssignment.objects.filter(
                teacher=teacher,
                offering__academic_year=academic_year,
            ).select_related('offering')
        )
        taught_ids = {assignment.offering_id for assignment in taught_assignments}
        roles_by_offering = {
            assignment.offering_id: assignment.role
            for assignment in taught_assignments
        }

        homeroom_class_group_ids = set(
            HomeroomTeacherAssignment.objects.filter(
                teacher=teacher,
                academic_year=academic_year,
            ).values_list('class_group_id', flat=True)
        )

        offerings = list(
            SubjectOffering.objects.filter(
                Q(id__in=taught_ids) | Q(class_group_id__in=homeroom_class_group_ids),
                academic_year=academic_year,
                subject__status='active',
            )
            .select_related(*OFFERING_SELECT_RELATED)
            .distinct()
            .order_by(
                'class_group__grade_level__number',
                'class_group__letter',
                'subject__name',
                'id',
            )
        )

        rows = []
        for offering in offerings:
            access, taught, homeroom = _access_for(
                offering, taught_ids, homeroom_class_group_ids,
            )
            row = offering_payload(offering)
            row.update({
                'subject_language_group': offering.subject.language_group,
                'class_group_id': offering.class_group_id,
                'class_group_detail': class_group_payload(offering.class_group),
                'academic_year_id': offering.academic_year_id,
                'access': access,
                'teaching_role': roles_by_offering.get(offering.id),
                'is_homeroom_class': homeroom,
                'can_heatmap': taught,
            })
            rows.append(row)

        return Response({
            'teacher': _teacher_payload(teacher),
            'academic_year': academic_year_payload(academic_year),
            'offerings': rows,
            'count': len(rows),
        })


class StudentAssignmentSummaryAPIView(APIView):
    """
    GET analytics/students/<student_id>/assignment-summary/

    One axis per subject the student's class is taught, built from assignment
    marks, with the class mean, the student's percentile, and the lesson / exam
    / final split on each.

    Axes are ordered by subject name, never by value: reordering by value makes
    the shape meaningless between quarters. A subject with no assignments in
    scope still gets an axis, at 0.0 with assignment_count 0, so the vertex
    count holds steady — read assignment_count before reading value.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentAssignmentSummarySerializer,
        parameters=[
            ACADEMIC_YEAR_PARAM,
            OpenApiParameter(
                'quarter', int,
                description=(
                    'Quarter, 1–4. Assignments carry only a date, so this means '
                    "the academic year's own q<n>_start … q<n>_end window — a "
                    '400 when the year has no dates for that quarter. Default: '
                    'the whole year.'
                ),
            ),
            CATEGORY_PARAM,
            OpenApiParameter(
                'date_from', OpenApiTypes.DATE,
                description='Earliest assignment date. Overrides quarter.',
            ),
            OpenApiParameter(
                'date_to', OpenApiTypes.DATE,
                description='Latest assignment date. Overrides quarter.',
            ),
            MISSING_PARAM,
            OpenApiParameter(
                'include_class_mean', bool,
                description='Include class mean and percentile. Default true.',
            ),
        ],
        description=(
            'Per-subject standing for one student, from subject assignments. '
            'Every axis carries a lesson / exam / final breakdown, which is '
            'where this differs from the topic-grade radar: it is the split '
            'that shows a student who is fine on classwork and falls over in '
            'exams.'
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

        missing = choice_param(
            request.query_params, 'missing', MISSING_CHOICES, 'exclude',
        )
        include_class_mean = bool_param(
            request.query_params, 'include_class_mean', True,
        )

        year_id = int_param(request.query_params, 'academic_year', 1)
        if year_id is not None:
            academic_year = get_object_or_404(AcademicYear, pk=year_id)
        else:
            academic_year = AcademicYear.objects.filter(is_active=True).first()
        if academic_year is None:
            return Response(self._empty(student, None, None, missing))

        quarter = int_param(request.query_params, 'quarter', 1, 4)
        filters = self._filters(request.query_params, academic_year, quarter)
        filters['missing'] = missing

        enrollment = Enrollment.objects.filter(
            student=student, academic_year=academic_year, status='active',
        ).select_related('class_group', 'class_group__grade_level').first()
        if enrollment is None:
            payload = self._empty(student, academic_year, quarter, missing)
            payload['filters'] = filters
            return Response(payload)

        offerings = list(
            SubjectOffering.objects.filter(
                class_group=enrollment.class_group,
                academic_year=academic_year,
            ).select_related('subject').order_by('subject__name', 'id')
        )
        cohort = (
            enrolled_students(enrollment.class_group_id, academic_year.id)
            if include_class_mean else [student]
        )

        assignments = self._assignments(offerings, filters)
        by_offering = defaultdict(list)
        for assignment in assignments:
            by_offering[assignment.offering_id].append(assignment)

        percents, _raw, _grade_ids, _comments = assignment_percent_matrix(
            assignments, cohort,
        )

        axes = []
        for offering in offerings:
            own = by_offering.get(offering.id, [])
            values = _values_for(
                percents, [(a.id, student.id) for a in own], missing,
            )
            axis = {
                'offering_id': offering.id,
                'subject_id': offering.subject_id,
                'subject': offering.subject.name,
                'language_group': offering.subject.language_group,
                'value': mean(values),
                'assignment_count': len(own),
                'graded_count': sum(
                    1 for a in own if percents.get((a.id, student.id)) is not None
                ),
                'by_category': _category_breakdown(own, percents, student, missing),
            }
            if include_class_mean:
                class_values = [
                    mean(_values_for(
                        percents, [(a.id, other.id) for a in own], missing,
                    ))
                    for other in cohort
                ]
                axis['class_mean'] = mean(class_values)
                axis['percentile'] = percentile_rank(class_values, axis['value'])
            axes.append(axis)

        return Response({
            'student': student_payload(student),
            'academic_year': academic_year_payload(academic_year),
            'class_group': class_group_payload(enrollment.class_group),
            'filters': filters,
            'grading': _grading_note(missing),
            'axes': axes,
            'summary': self._summary(axes, include_class_mean),
        })

    # ── payload assembly ──

    @staticmethod
    def _filters(params, academic_year, quarter):
        """
        Category, quarter and date range, resolved into one date window.

        An explicit date_from / date_to always wins over the quarter it would
        otherwise be derived from, so a caller can ask for a fortnight inside a
        quarter without the two fighting.
        """
        category = choice_param(params, 'category', set(CATEGORIES), None)
        date_from = date_param(params, 'date_from')
        date_to = date_param(params, 'date_to')

        if quarter is not None:
            start, end = require_quarter_window(academic_year, quarter)
            date_from = date_from or start
            date_to = date_to or end

        return {
            'category': category,
            'quarter': quarter,
            'date_from': date_from.isoformat() if date_from else None,
            'date_to': date_to.isoformat() if date_to else None,
        }

    @staticmethod
    def _assignments(offerings, filters):
        if not offerings:
            return []
        queryset = SubjectAssignment.objects.filter(
            offering__in=offerings,
        ).select_related(*ASSIGNMENT_SELECT_RELATED)
        if filters['category']:
            queryset = queryset.filter(category=filters['category'])
        if filters['date_from']:
            queryset = queryset.filter(date__gte=filters['date_from'])
        if filters['date_to']:
            queryset = queryset.filter(date__lte=filters['date_to'])
        return list(queryset.order_by('date', 'created_at', 'id'))

    @staticmethod
    def _empty(student, academic_year, quarter, missing):
        return {
            'student': student_payload(student),
            'academic_year': academic_year_payload(academic_year),
            'class_group': None,
            'filters': {
                'category': None,
                'quarter': quarter,
                'date_from': None,
                'date_to': None,
                'missing': missing,
            },
            'grading': _grading_note(missing),
            'axes': [],
            'summary': {
                'overall_mean': 0.0,
                'class_overall_mean': None,
                'strongest': None,
                'weakest': None,
                'axis_count': 0,
                'subject_count': 0,
                'assignment_count': 0,
                'graded_count': 0,
                'by_category': {
                    category: {'assignment_count': 0, 'graded_count': 0, 'value': 0.0}
                    for category in CATEGORIES
                },
            },
        }

    @staticmethod
    def _summary(axes, include_class_mean):
        """
        Aggregates over the axes that actually have assignments behind them.

        An axis with assignment_count 0 stays on the chart so the vertex count
        holds steady, but it means "this subject set no work", not "the student
        scored zero". Averaging it in would drag overall_mean down and hand
        `weakest` to whichever subject simply has not started yet.
        """
        scored = [axis for axis in axes if axis['assignment_count'] > 0]

        strongest = max(scored, key=lambda a: a['value']) if scored else None
        weakest = min(scored, key=lambda a: a['value']) if scored else None

        by_category = {}
        for category in CATEGORIES:
            blocks = [axis['by_category'][category] for axis in axes]
            with_work = [b for b in blocks if b['assignment_count'] > 0]
            by_category[category] = {
                'assignment_count': sum(b['assignment_count'] for b in blocks),
                'graded_count': sum(b['graded_count'] for b in blocks),
                'value': mean([b['value'] for b in with_work]),
            }

        summary = {
            'overall_mean': mean([axis['value'] for axis in scored]),
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
            'assignment_count': sum(axis['assignment_count'] for axis in axes),
            'graded_count': sum(axis['graded_count'] for axis in axes),
            'by_category': by_category,
        }
        if include_class_mean and scored:
            summary['class_overall_mean'] = mean(
                [axis['class_mean'] for axis in scored]
            )
        return summary
