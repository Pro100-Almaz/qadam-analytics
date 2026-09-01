"""
Pieces shared by the analytics endpoints.

Three modules sit on top of this one, one per source of numbers:

- analytics.py            TopicGrade → Topic → Lesson. Weighted lesson grades.
- analytics_subject.py    SubjectGrade → SubjectAssignment → SubjectOffering.
                          Assignment marks, as a percent of each assignment's
                          own max_grade.
- analytics_attendance.py ScheduleAttendance → ScheduleSession → SubjectSchedule.
                          Present / absent rates.

What lives here is what all three need and none of them owns: query-parameter
parsing, the small statistics, the student / offering / class-group payload
shapes, and the two "may this caller see the whole class" checks. The grading
semantics do *not* live here — each module documents its own, because they
genuinely differ: a missing TopicGrade is a zero, a missing SubjectGrade is
unmarked work, and an unrecorded attendance row is a lesson nobody registered.

Nothing here writes.
"""

import math

from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from rest_framework.exceptions import ValidationError

from apps.authentication.models import Teacher
from apps.home.models import Enrollment, TeachingAssignment
from core.permissions import (
    is_admin_role,
    is_teacher_role,
    teacher_homeroom_class_group_ids,
)


OFFERING_SELECT_RELATED = (
    'subject', 'class_group', 'class_group__grade_level', 'academic_year',
)


# ── Query parameter parsing ──

def int_param(params, name, minimum=None, maximum=None):
    """An optional positive-integer query param, or None. Out of range is a 400."""
    raw = params.get(name)
    if raw in (None, ''):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: f'{name} must be an integer.'})
    if minimum is not None and value < minimum:
        raise ValidationError({name: f'{name} must be between {minimum} and {maximum}.'})
    if maximum is not None and value > maximum:
        raise ValidationError({name: f'{name} must be between {minimum} and {maximum}.'})
    return value


def float_param(params, name, minimum=None, maximum=None):
    """An optional float query param, or None. Out of range is a 400."""
    raw = params.get(name)
    if raw in (None, ''):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: f'{name} must be a number.'})
    if minimum is not None and value < minimum:
        raise ValidationError({name: f'{name} must be between {minimum} and {maximum}.'})
    if maximum is not None and value > maximum:
        raise ValidationError({name: f'{name} must be between {minimum} and {maximum}.'})
    return value


def date_param(params, name):
    """An optional ISO date query param, or None."""
    raw = params.get(name)
    if raw in (None, ''):
        return None
    value = parse_date(raw)
    if value is None:
        raise ValidationError({name: f'{name} must be an ISO date (YYYY-MM-DD).'})
    return value


def bool_param(params, name, default):
    raw = params.get(name)
    if raw in (None, ''):
        return default
    return str(raw).lower() in ('1', 'true', 'yes')


def choice_param(params, name, choices, default):
    raw = params.get(name)
    if raw in (None, ''):
        return default
    if raw not in choices:
        raise ValidationError({
            name: f"{name} must be one of: {', '.join(sorted(choices))}.",
        })
    return raw


# ── Statistics ──

def mean(values):
    return round(sum(values) / len(values), 2) if values else 0.0


def percentile(sorted_values, fraction):
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)

    position = fraction * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return round(sorted_values[low], 2)

    weight = position - low
    return round(
        sorted_values[low] * (1 - weight) + sorted_values[high] * weight, 2,
    )


def rank(values, value):
    """1-based rank, best first. Ties share the better rank."""
    return sum(1 for other in values if other > value) + 1


def percentile_rank(values, value):
    """
    Percent of the class at or below `value`, counting ties as half.

    The midpoint convention matters here: with the zero-fill rule a whole
    ungraded class sits on 0.0 together, and the naive "share strictly below"
    would report every one of them at the 0th percentile.
    """
    if not values:
        return 0
    below = sum(1 for other in values if other < value)
    equal = sum(1 for other in values if other == value)
    return int(round(100 * (below + 0.5 * equal) / len(values)))


def trend_slope(values):
    """Least-squares slope in points per step. 0.0 for fewer than two points."""
    count = len(values)
    if count < 2:
        return 0.0

    mean_x = (count - 1) / 2
    mean_y = sum(values) / count
    numerator = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(count))
    return round(numerator / denominator, 4) if denominator else 0.0


def ratio(part, total):
    """`part` as a percentage of `total`. 0.0 rather than a division error."""
    return round(100 * part / total, 2) if total else 0.0


def band(values):
    """
    The mean / median / quartile / min / max block drawn around a single point.

    Every analytics chart that shows one subject against their class draws the
    same five numbers, so they are computed in one place and named the same way
    in every payload.
    """
    ordered = sorted(values)
    return {
        'mean': mean(ordered),
        'median': percentile(ordered, 0.5),
        'p25': percentile(ordered, 0.25),
        'p75': percentile(ordered, 0.75),
        'min': round(ordered[0], 2) if ordered else 0.0,
        'max': round(ordered[-1], 2) if ordered else 0.0,
    }


# ── Payload shapes ──

def student_payload(student):
    full_name = student.user.get_full_name().strip() or student.user.username
    first = student.user.first_name.strip()
    last = student.user.last_name.strip()
    short_name = f'{first[0]}. {last}' if first and last else full_name
    return {'id': student.id, 'full_name': full_name, 'short_name': short_name}


def offering_payload(offering):
    return {
        'id': offering.id,
        'subject': offering.subject.name,
        'subject_id': offering.subject_id,
        'class_group': str(offering.class_group) if offering.class_group_id else None,
        'academic_year': str(offering.academic_year) if offering.academic_year_id else None,
        'max_points': offering.max_points,
        'grading_strategy': offering.grading_strategy,
    }


def class_group_payload(class_group):
    return {
        'id': class_group.id,
        'name': str(class_group),
        'grade_level': (
            class_group.grade_level.number if class_group.grade_level_id else None
        ),
        'letter': class_group.letter,
        'academic_year': (
            str(class_group.academic_year) if class_group.academic_year_id else None
        ),
    }


def academic_year_payload(academic_year):
    if academic_year is None:
        return None
    return {'id': academic_year.id, 'year': academic_year.year}


# ── Cohorts ──

def enrolled_students(class_group_id, academic_year_id=None):
    """
    Students actively enrolled in one class group, in class-list order.

    `academic_year_id` None means every year the class group has run, which is
    only ever the right question for a class group that has no year of its own.
    """
    queryset = Enrollment.objects.filter(
        class_group_id=class_group_id, status='active',
    )
    if academic_year_id is not None:
        queryset = queryset.filter(academic_year_id=academic_year_id)

    return [
        enrollment.student
        for enrollment in queryset.select_related(
            'student', 'student__user',
        ).order_by(
            'student__user__last_name', 'student__user__first_name', 'student_id',
        )
    ]


def class_students(offering):
    """Students actively enrolled in the offering's class group, in list order."""
    return enrolled_students(offering.class_group_id, offering.academic_year_id)


def student_is_enrolled_in(student, offering):
    return Enrollment.objects.filter(
        student=student,
        class_group_id=offering.class_group_id,
        academic_year_id=offering.academic_year_id,
        status='active',
    ).exists()


# ── Class-wide read access ──

def can_read_class_wide(user, offering):
    """
    Whether the caller may see every student's numbers in one offering.

    Teachers of the offering, the homeroom teacher of its class group,
    psychologists and admin roles. Deliberately not students or parents.
    """
    if is_admin_role(user) or user.is_psychologist():
        return True

    if not is_teacher_role(user):
        return False

    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return False

    if TeachingAssignment.objects.filter(
        offering=offering, teacher=teacher,
    ).exists():
        return True

    return offering.class_group_id in set(
        teacher_homeroom_class_group_ids(teacher)
    )


def can_read_class_group_wide(user, class_group):
    """
    The same check one level up: every student of a class group, every subject.

    Wider than can_read_class_wide() in reach but not in audience — it is the
    homeroom teacher's view, so any teacher who teaches the class group at all
    qualifies, along with its homeroom teacher, psychologists and admin roles.
    Students and parents do not.
    """
    if is_admin_role(user) or user.is_psychologist():
        return True

    if not is_teacher_role(user):
        return False

    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return False

    if class_group.id in set(teacher_homeroom_class_group_ids(teacher)):
        return True

    return TeachingAssignment.objects.filter(
        teacher=teacher, offering__class_group_id=class_group.id,
    ).exists()


# ── Quarters ──

def quarter_window(academic_year, quarter):
    """
    The (start, end) dates of one quarter of an academic year.

    Either end can be None when the year has not been given dates. Lessons
    carry their own `quarter` field and never need this; subject assignments
    and attendance rows carry only a date, so a quarter filter for them means
    a date range and nothing else.
    """
    if academic_year is None or quarter is None:
        return None, None
    return (
        getattr(academic_year, f'q{quarter}_start', None),
        getattr(academic_year, f'q{quarter}_end', None),
    )


def require_quarter_window(academic_year, quarter):
    """
    quarter_window(), but a 400 when the year has no dates for that quarter.

    Silently ignoring the filter would hand back a full year of rows labelled
    as one quarter, which is worse than refusing.
    """
    start, end = quarter_window(academic_year, quarter)
    if start is None or end is None:
        raise ValidationError({
            'quarter': (
                f'Academic year {academic_year} has no start and end dates for '
                f'quarter {quarter}. Set them, or filter by date_from / date_to '
                f'instead.'
            ),
        })
    return start, end


# ── Filter parameters, for the schema ──

DATE_RANGE_PARAMS = [
    OpenApiParameter(
        'date_from', OpenApiTypes.DATE, description='Earliest date, inclusive.',
    ),
    OpenApiParameter(
        'date_to', OpenApiTypes.DATE, description='Latest date, inclusive.',
    ),
]

ACADEMIC_YEAR_PARAM = OpenApiParameter(
    'academic_year', int, description='Academic year id. Default: the active year.',
)

QUARTER_PARAM = OpenApiParameter(
    'quarter', int, description='Quarter, 1–4. Default: all.',
)
