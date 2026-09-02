"""
Read-only analytics endpoints over attendance.

Three shapes over ScheduleAttendance → ScheduleSession → SubjectSchedule →
SubjectOffering:

- students/<id>/attendance-summary/        one student's attendance across
                   every subject, split by subject, weekday and month, with
                   the class rate beside it. The "is this student turning up"
                   view, and the one a parent may call.
- offerings/<id>/attendance-heatmap/       every student × every registered
                   slot of one offering. A dark column is a day half the class
                   missed; a dark row is a student who has stopped coming.
- class-groups/<id>/attendance-overview/   one class group, every subject,
                   ranked by attendance rate, with an at-risk list.

Counting semantics — the whole module
-------------------------------------
An attendance row exists only where somebody registered one. There is no
roster of expected sessions to compare against, so **an unrecorded slot is not
an absence** and is never counted as one: rates are `present / (present +
absent)` over the rows that exist, and `recorded` travels next to every rate to
say how thin the ground under it is. A student with nothing recorded reads a
rate of 0.0 with `recorded` 0 — read `recorded` before reading the rate, the
same way the grade analytics ask you to read `lesson_count` before `value`.

`weekday` is the session's own weekday, 0 = Monday through 6 = Sunday, matching
ScheduleSession.weekday.

Read access:
- Summary        — can_access_student(): the student, their parents, teachers
                   who teach them, their homeroom teacher, psychologists, and
                   Admin / Principal / Supervisor. The class comparison it
                   carries is aggregate only — a rate and a rank, never a name.
- Heatmap        — teachers of the offering, the homeroom teacher of its class
                   group, psychologists and admin roles.
- Overview       — any teacher of that class group, its homeroom teacher,
                   psychologists and admin roles. Students and parents get 403.
Nothing here writes.
"""

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student
from apps.home.models import AcademicYear, ClassGroup, Enrollment, SubjectOffering
from apps.lesson.models import ScheduleAttendance
from core.error_messages import NO_PERMISSION
from core.permissions import can_access_student

from apps.lesson.api.analytics_common import (
    ACADEMIC_YEAR_PARAM,
    DATE_RANGE_PARAMS,
    OFFERING_SELECT_RELATED,
    QUARTER_PARAM,
    academic_year_payload,
    bool_param,
    can_read_class_group_wide,
    can_read_class_wide,
    class_group_payload,
    class_students,
    date_param,
    enrolled_students,
    float_param,
    int_param,
    mean,
    offering_payload,
    percentile_rank,
    rank,
    ratio,
    student_payload,
)
from apps.lesson.api.serializers import (
    ClassGroupAttendanceOverviewSerializer,
    OfferingAttendanceHeatmapSerializer,
    StudentAttendanceSummarySerializer,
)


# How the unrecorded-slot rule is reported back to the client, so a frontend
# never has to assume it.
COUNTING_NOTE = {
    'unrecorded_as': 'excluded',
    'rate': 'present / (present + absent)',
}

WEEKDAYS = list(range(7))

# A year of daily registers for one subject runs past what a heatmap can show.
# Keep the most recent slots and say so in the payload.
MAX_HEATMAP_COLUMNS = 90

# Below this attendance rate a student lands on the at-risk list, unless the
# caller says otherwise.
DEFAULT_AT_RISK_BELOW = 90.0


# ── Counting ──

def tally(queryset, *group_fields):
    """
    present / absent / recorded counts, grouped in the database.

    One query however many groups come back, which is the only reason these
    endpoints can span a year of registers without loading a row of it.
    """
    return queryset.values(*group_fields).annotate(
        recorded=Count('id'),
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
    ).order_by(*group_fields)


def counts(present=0, absent=0, recorded=None):
    """The four numbers every block in this module reports."""
    return {
        'recorded': recorded if recorded is not None else present + absent,
        'present': present,
        'absent': absent,
        'attendance_rate': ratio(present, present + absent),
    }


def counts_from(row):
    return counts(row['present'], row['absent'], row['recorded'])


# ── Filters ──

def apply_attendance_filters(queryset, params, academic_year=None):
    """
    Narrow attendance by quarter / date range, and echo the filters back.

    `quarter` here is the schedule's own quarter rather than a date window:
    SubjectSchedule is created per quarter, so the field is exact and needs no
    academic calendar behind it.
    """
    quarter = int_param(params, 'quarter', 1, 4)
    date_from = date_param(params, 'date_from')
    date_to = date_param(params, 'date_to')

    if quarter is not None:
        queryset = queryset.filter(session__schedule__quarter=quarter)
    if date_from is not None:
        queryset = queryset.filter(date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(date__lte=date_to)

    return queryset, {
        'academic_year': academic_year.id if academic_year else None,
        'quarter': quarter,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
    }


def by_weekday(queryset):
    """Seven blocks, Monday first, whether or not anything was registered."""
    tallied = {
        row['session__weekday']: counts_from(row)
        for row in tally(queryset, 'session__weekday')
    }
    return [
        dict(weekday=weekday, **tallied.get(weekday, counts()))
        for weekday in WEEKDAYS
    ]


def by_month(queryset):
    """One block per calendar month that has rows, oldest first."""
    rows = queryset.annotate(month=TruncMonth('date')).values('month').annotate(
        recorded=Count('id'),
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
    ).order_by('month')
    return [
        dict(
            month=row['month'].strftime('%Y-%m') if row['month'] else None,
            **counts_from(row),
        )
        for row in rows
    ]


def by_offering(queryset):
    """
    One block per subject, by subject name.

    A schedule with no offering has no subject either, so it is labelled by its
    own description and reports `offering_id` null.
    """
    rows = tally(
        queryset,
        'session__schedule__offering_id',
        'session__schedule__offering__subject__name',
        'session__schedule__description',
    )
    blocks = [
        dict(
            offering_id=row['session__schedule__offering_id'],
            subject=(
                row['session__schedule__offering__subject__name']
                or row['session__schedule__description']
                or ''
            ),
            **counts_from(row),
        )
        for row in rows
    ]
    return sorted(
        blocks, key=lambda block: (block['subject'], block['offering_id'] or 0),
    )


def rates_by_student(queryset, students):
    """
    student_id -> the four counts, dense over `students`.

    Students with nothing registered are filled in at zero rather than left
    out: they are exactly the ones a homeroom teacher is looking for, and a
    missing row would hide them.
    """
    tallied = {
        row['student_id']: counts_from(row)
        for row in tally(queryset, 'student_id')
    }
    return {student.id: tallied.get(student.id, counts()) for student in students}


ATTENDANCE_FILTER_PARAMS = [QUARTER_PARAM] + DATE_RANGE_PARAMS


class StudentAttendanceSummaryAPIView(APIView):
    """
    GET analytics/students/<student_id>/attendance-summary/

    One student's attendance over a year, a quarter or a date range, totalled
    and then cut three ways — by subject, by weekday and by month.

    The weekday split is the one that earns its place: a student who is absent
    every Monday first period is a different problem from one who is absent at
    random, and the totals alone cannot tell them apart.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentAttendanceSummarySerializer,
        parameters=[ACADEMIC_YEAR_PARAM] + ATTENDANCE_FILTER_PARAMS + [
            OpenApiParameter('offering', int, description='Limit to one subject offering.'),
            OpenApiParameter(
                'include_class_stats', bool,
                description=(
                    "Include the class's own attendance rate, this student's "
                    'rank in it and their percentile. Aggregate only — no '
                    'classmate is named. Default true.'
                ),
            ),
        ],
        description=(
            'Attendance totals and breakdowns for one student. Unrecorded '
            'slots are never counted as absences, so read `recorded` next to '
            'every rate. `quarter` filters on the schedule\'s own quarter.'
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

        include_class_stats = bool_param(
            request.query_params, 'include_class_stats', True,
        )

        year_id = int_param(request.query_params, 'academic_year', 1)
        if year_id is not None:
            academic_year = get_object_or_404(AcademicYear, pk=year_id)
        else:
            academic_year = AcademicYear.objects.filter(is_active=True).first()

        scope = ScheduleAttendance.objects.all()
        if academic_year is not None:
            scope = scope.filter(
                session__schedule__offering__academic_year_id=academic_year.id,
            )
        scope, filters = apply_attendance_filters(
            scope, request.query_params, academic_year,
        )

        offering_id = int_param(request.query_params, 'offering', 1)
        if offering_id is not None:
            scope = scope.filter(session__schedule__offering_id=offering_id)
        filters['offering'] = offering_id

        own = scope.filter(student=student)
        totals = self._totals(own)

        payload = {
            'student': student_payload(student),
            'academic_year': academic_year_payload(academic_year),
            'class_group': None,
            'filters': filters,
            'counting': COUNTING_NOTE,
            'totals': totals,
            'by_subject': by_offering(own),
            'by_weekday': by_weekday(own),
            'by_month': by_month(own),
            'class_comparison': None,
        }

        enrollment = Enrollment.objects.filter(
            student=student, academic_year=academic_year, status='active',
        ).select_related('class_group', 'class_group__grade_level').first() if academic_year else None
        if enrollment is not None:
            payload['class_group'] = class_group_payload(enrollment.class_group)
            if include_class_stats:
                payload['class_comparison'] = self._class_comparison(
                    scope, enrollment, academic_year, student, totals,
                )

        return Response(payload)

    @staticmethod
    def _totals(queryset):
        row = queryset.aggregate(
            recorded=Count('id'),
            present=Count('id', filter=Q(status='present')),
            absent=Count('id', filter=Q(status='absent')),
        )
        return counts_from(row)

    @staticmethod
    def _class_comparison(scope, enrollment, academic_year, student, totals):
        """
        The student's rate against their classmates', without naming any.

        `class_attendance_rate` is the class's pooled rate — every registered
        row of the class over every present one — rather than the mean of the
        per-student rates, so a student with four rows does not swing it as far
        as one with four hundred. The mean of the per-student rates is reported
        beside it as `class_mean_rate`, since that is the number a rank is
        actually taken over.
        """
        cohort = enrolled_students(enrollment.class_group_id, academic_year.id)
        cohort_rows = scope.filter(student__in=cohort)

        per_student = rates_by_student(cohort_rows, cohort)
        rates = [block['attendance_rate'] for block in per_student.values()]
        pooled = cohort_rows.aggregate(
            recorded=Count('id'),
            present=Count('id', filter=Q(status='present')),
            absent=Count('id', filter=Q(status='absent')),
        )

        own_rate = totals['attendance_rate']
        return {
            'class_size': len(cohort),
            'class_attendance_rate': counts_from(pooled)['attendance_rate'],
            'class_mean_rate': mean(rates),
            'rank': rank(rates, own_rate),
            'percentile': percentile_rank(rates, own_rate),
            'delta': round(own_rate - mean(rates), 2),
        }


class OfferingAttendanceHeatmapAPIView(APIView):
    """
    GET analytics/offerings/<offering_id>/attendance-heatmap/

    Every student of one offering against every slot that was actually
    registered, as a matrix rather than a list of cells.

    A column is one (date, session) pair, not one date: a subject taught twice
    on a Tuesday produces two columns, because collapsing them would turn "here
    for one of two lessons" into a number that means neither.

    `matrix[i][j]` is `students[i]` at `slots[j]` — "present", "absent", or
    null where nothing was registered. This is the one payload in the analytics
    modules that is deliberately nullable: an unregistered slot is not an
    absence and must not be drawn as one.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=OfferingAttendanceHeatmapSerializer,
        parameters=ATTENDANCE_FILTER_PARAMS,
        description=(
            'Student × slot attendance matrix for one offering. Cells are '
            '"present", "absent" or null for nothing registered. Capped at the '
            f'{MAX_HEATMAP_COLUMNS} most recent slots, with `truncated` set '
            'when the cap bit. Teachers of the offering, its homeroom teacher, '
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

        rows, filters = apply_attendance_filters(
            ScheduleAttendance.objects.filter(
                session__schedule__offering_id=offering.id,
            ),
            request.query_params,
            offering.academic_year,
        )
        students = class_students(offering)

        slots, truncated = self._slots(rows)
        status_by_cell = {
            (row['date'], row['session_id'], row['student_id']): row['status']
            for row in rows.values('date', 'session_id', 'student_id', 'status')
        }

        matrix = []
        row_summary = []
        for student in students:
            line = []
            present = absent = 0
            for slot in slots:
                value = status_by_cell.get(
                    (slot['date'], slot['session_id'], student.id)
                )
                line.append(value)
                if value == 'present':
                    present += 1
                elif value == 'absent':
                    absent += 1
            matrix.append(line)
            row_summary.append(counts(present, absent))

        column_summary = []
        for index, slot in enumerate(slots):
            present = sum(1 for line in matrix if line[index] == 'present')
            absent = sum(1 for line in matrix if line[index] == 'absent')
            column_summary.append(counts(present, absent))

        return Response({
            'offering': offering_payload(offering),
            'filters': filters,
            'counting': COUNTING_NOTE,
            'legend': ['present', 'absent', None],
            'students': [student_payload(student) for student in students],
            'slots': [
                {
                    'key': f"{slot['date'].isoformat()}:{slot['session_id']}",
                    'date': slot['date'].isoformat(),
                    'session_id': slot['session_id'],
                    'time_start': slot['time_start'].isoformat(),
                    'time_end': slot['time_end'].isoformat(),
                    'weekday': slot['weekday'],
                    'quarter': slot['quarter'],
                }
                for slot in slots
            ],
            'matrix': matrix,
            'row_summary': row_summary,
            'column_summary': column_summary,
            'totals': self._totals(row_summary),
            'class_size': len(students),
            'slot_count': len(slots),
            'truncated': truncated,
        })

    @staticmethod
    def _slots(rows):
        """
        The (date, session) pairs that carry rows, oldest first.

        Ordered newest-first for the cap so that an offering with a year of
        registers keeps its recent weeks, then reversed for the payload — a
        chart reads left to right in time.
        """
        distinct = list(
            rows.values(
                'date', 'session_id', 'session__time_start', 'session__time_end',
                'session__weekday', 'session__schedule__quarter',
            ).distinct().order_by('-date', '-session__time_start', '-session_id')
        )
        truncated = len(distinct) > MAX_HEATMAP_COLUMNS
        if truncated:
            distinct = distinct[:MAX_HEATMAP_COLUMNS]

        return [
            {
                'date': row['date'],
                'session_id': row['session_id'],
                'time_start': row['session__time_start'],
                'time_end': row['session__time_end'],
                'weekday': row['session__weekday'],
                'quarter': row['session__schedule__quarter'],
            }
            for row in reversed(distinct)
        ], truncated

    @staticmethod
    def _totals(row_summary):
        return counts(
            sum(block['present'] for block in row_summary),
            sum(block['absent'] for block in row_summary),
        )


class ClassGroupAttendanceOverviewAPIView(APIView):
    """
    GET analytics/class-groups/<class_group_id>/attendance-overview/

    One class group, every subject taught to it, every student ranked by
    attendance rate, plus the list of students who fall below a threshold.

    This is the homeroom teacher's register: the offering heatmap answers "who
    missed my lessons", and this answers "who is missing school".
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=ClassGroupAttendanceOverviewSerializer,
        parameters=ATTENDANCE_FILTER_PARAMS + [
            ACADEMIC_YEAR_PARAM,
            OpenApiParameter(
                'at_risk_below', float,
                description=(
                    'Attendance rate below which a student is listed as at '
                    f'risk. Default {DEFAULT_AT_RISK_BELOW}. Students with '
                    'nothing registered are never listed — there is no '
                    'evidence either way.'
                ),
            ),
        ],
        description=(
            'Attendance across a whole class group. Students are ranked best '
            'first and ties share the better rank; a student with nothing '
            'registered still appears, at a rate of 0.0 with `recorded` 0. Any '
            'teacher of the class group, its homeroom teacher, psychologists '
            'and admin roles only.'
        ),
    )
    def get(self, request, class_group_id):
        class_group = get_object_or_404(
            ClassGroup.objects.select_related('grade_level', 'academic_year'),
            pk=class_group_id,
        )
        if not can_read_class_group_wide(request.user, class_group):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )

        year_id = int_param(request.query_params, 'academic_year', 1)
        if year_id is not None:
            academic_year = get_object_or_404(AcademicYear, pk=year_id)
        else:
            academic_year = (
                class_group.academic_year
                or AcademicYear.objects.filter(is_active=True).first()
            )

        at_risk_below = float_param(
            request.query_params, 'at_risk_below', 0, 100,
        )
        if at_risk_below is None:
            at_risk_below = DEFAULT_AT_RISK_BELOW

        students = enrolled_students(
            class_group.id, academic_year.id if academic_year else None,
        )
        rows = ScheduleAttendance.objects.filter(
            student__in=students,
            session__schedule__class_group_id=class_group.id,
        )
        if academic_year is not None:
            rows = rows.filter(
                session__schedule__class_group__academic_year_id=academic_year.id,
            )
        rows, filters = apply_attendance_filters(
            rows, request.query_params, academic_year,
        )
        filters['at_risk_below'] = at_risk_below

        per_student = rates_by_student(rows, students)
        rates = [per_student[student.id]['attendance_rate'] for student in students]

        student_blocks = [
            dict(
                student=student_payload(student),
                rank=rank(rates, per_student[student.id]['attendance_rate']),
                **per_student[student.id],
            )
            for student in students
        ]
        student_blocks.sort(
            key=lambda block: (-block['attendance_rate'], block['student']['full_name'])
        )

        at_risk = [
            block for block in student_blocks
            if block['recorded'] > 0 and block['attendance_rate'] < at_risk_below
        ]

        pooled = rows.aggregate(
            recorded=Count('id'),
            present=Count('id', filter=Q(status='present')),
            absent=Count('id', filter=Q(status='absent')),
        )
        totals = counts_from(pooled)
        totals['class_size'] = len(students)
        totals['mean_student_rate'] = mean(rates)

        return Response({
            'class_group': class_group_payload(class_group),
            'academic_year': academic_year_payload(academic_year),
            'filters': filters,
            'counting': COUNTING_NOTE,
            'totals': totals,
            'students': student_blocks,
            'by_subject': by_offering(rows),
            'by_weekday': by_weekday(rows),
            'by_month': by_month(rows),
            'at_risk': at_risk,
        })
