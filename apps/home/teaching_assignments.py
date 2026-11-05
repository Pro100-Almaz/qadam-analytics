"""Temporal TeachingAssignment queries and replacement workflow (spec 0015)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.authentication.models import Teacher
from apps.home.models import TeachingAssignment


def assignment_for(user, offering, effective_date, *, writes=False):
    """Return one caller TA covering ``effective_date``, or ``None``."""
    if effective_date is None:
        return None
    if writes and offering.academic_year.archived:
        return None
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return None
    return TeachingAssignment.objects.filter(
        offering=offering,
        teacher=teacher,
        start_date__lte=effective_date,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=effective_date),
    ).first()


def teacher_can_write(user, offering, effective_date):
    return assignment_for(
        user, offering, effective_date, writes=True,
    ) is not None


def request_can_write(request, offering, effective_date):
    """Serializer-friendly check with one period query per request, not row."""
    if effective_date is None or offering.academic_year.archived:
        return False
    cache = getattr(request, '_teaching_period_cache', None)
    if cache is None:
        teacher = Teacher.objects.filter(user=request.user).first()
        cache = [] if teacher is None else list(
            TeachingAssignment.objects.filter(teacher=teacher).values(
                'offering_id', 'start_date', 'end_date',
            )
        )
        request._teaching_period_cache = cache
    return any(
        period['offering_id'] == offering.pk
        and period['start_date'] <= effective_date
        and (
            period['end_date'] is None
            or period['end_date'] >= effective_date
        )
        for period in cache
    )


def restrict_to_teacher_periods(
    queryset, teacher, *, offering_field, date_field,
):
    """SQL-filter rows to dates covered by one of ``teacher``'s TAs."""
    periods = TeachingAssignment.objects.filter(
        teacher=teacher,
        offering_id=OuterRef(offering_field),
        start_date__lte=OuterRef(date_field),
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=OuterRef(date_field)),
    )
    return queryset.filter(Exists(periods))


@transaction.atomic
def replace_assignment(*, assignment, new_teacher, effective_date, actor=None):
    """Replace an open assignment with ``new_teacher`` from D onward.

    If closing on D-1 would leave an invalid or one-day period, remove the
    superseded row instead. Such a short-lived row represents an admin
    correction, not a real teaching period.
    """
    current = TeachingAssignment._base_manager.select_for_update().get(
        pk=assignment.pk,
    )
    if current.is_deleted or current.end_date is not None:
        raise ValidationError(
            'Only an open teaching assignment can be replaced.'
        )
    if effective_date > timezone.localdate():
        raise ValidationError('Future teacher replacements are not supported.')
    if effective_date < current.start_date:
        raise ValidationError(
            'Replacement date cannot precede the current start date.'
        )
    if current.teacher_id == new_teacher.pk:
        raise ValidationError('The replacement teacher must be different.')

    if actor is not None:
        current._history_user = actor
    offering = current.offering
    role = current.role
    end_date = effective_date - timedelta(days=1)
    if end_date <= current.start_date:
        current.hard_delete()
    else:
        current.end_date = end_date
        current.save(update_fields=['end_date'])

    replacement = TeachingAssignment(
        offering=offering,
        teacher=new_teacher,
        role=role,
        start_date=effective_date,
    )
    if actor is not None:
        replacement._history_user = actor
    replacement.save()
    return replacement
