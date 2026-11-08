"""Quarter-based TeachingAssignment authorization helpers."""

from django.db.models import Exists, OuterRef

from apps.authentication.models import Teacher
from apps.home.models import TeachingAssignment


def assignment_for(user, offering, quarter, *, writes=False):
    """Return a caller TA authorizing the requested quarter, or ``None``."""
    if quarter is None:
        return None
    if writes and offering.academic_year.archived:
        return None
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return None
    assignments = TeachingAssignment.objects.filter(
        offering=offering,
        teacher=teacher,
        quarter__isnull=False,
    )
    if writes:
        assignments = assignments.filter(quarter=quarter)
    else:
        assignments = assignments.filter(quarter__gte=quarter)
    return assignments.order_by('quarter').first()


def teacher_can_write(user, offering, quarter):
    return assignment_for(
        user, offering, quarter, writes=True,
    ) is not None


def quarter_for_date_or_single_assignment(user, offering, day):
    """Resolve legacy date-only writes without granting ambiguous authority."""
    quarter = offering.academic_year.quarter_of(day)
    if quarter is not None:
        return quarter
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return None
    quarters = list(TeachingAssignment.objects.filter(
        teacher=teacher, offering=offering, quarter__isnull=False,
    ).values_list('quarter', flat=True)[:2])
    return quarters[0] if len(quarters) == 1 else None


def request_can_write(request, offering, quarter):
    """Serializer-friendly exact-quarter check cached once per request."""
    if quarter is None or offering.academic_year.archived:
        return False
    cache = getattr(request, '_teaching_quarter_cache', None)
    if cache is None:
        teacher = Teacher.objects.filter(user=request.user).first()
        cache = set() if teacher is None else set(
            TeachingAssignment.objects.filter(
                teacher=teacher, quarter__isnull=False,
            ).values_list(
                'offering_id', 'quarter',
            )
        )
        request._teaching_quarter_cache = cache
    return (offering.pk, quarter) in cache


def restrict_to_teacher_quarters(
    queryset, teacher, *, offering_field, quarter_field,
):
    """SQL-filter rows to quarters visible to ``teacher`` cumulatively."""
    assignments = TeachingAssignment.objects.filter(
        teacher=teacher,
        offering_id=OuterRef(offering_field),
        quarter__isnull=False,
        quarter__gte=OuterRef(quarter_field),
    )
    return queryset.filter(Exists(assignments))
