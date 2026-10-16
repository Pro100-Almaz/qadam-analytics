"""Spec 0013, AC-10 — club read paths leave soft-deleted children out."""

import datetime

import pytest
from django.urls import reverse

from apps.achievement.api.services import club_base_queryset
from core.factories import (
    ClassGroupFactory, ClubAttendanceFactory, ClubFactory, EnrollmentFactory,
    StudentFactory,
)

pytestmark = pytest.mark.django_db


def test_ac10_club_member_count_excludes_deleted_student():
    club = ClubFactory()
    live, deleted = StudentFactory.create_batch(2)
    club.members.add(live, deleted)
    deleted.delete()

    assert club_base_queryset().get(pk=club.pk).member_count_value == 1


def test_ac10_club_attendance_dates_exclude_deleted_attendance():
    kept = ClubAttendanceFactory(date=datetime.date(2026, 9, 7))
    ClubAttendanceFactory(session=kept.session, date=datetime.date(2026, 9, 14)).delete()

    club = club_base_queryset().get(pk=kept.session.club_id)

    assert club.attendance_dates_count_value == 1


def test_ac10_club_available_students_exclude_deleted_enrollment(
    authenticated_client, admin_user,
):
    class_group = ClassGroupFactory()
    EnrollmentFactory(class_group=class_group).delete()
    club = ClubFactory()

    response = authenticated_client(admin_user).get(
        reverse('achievement-api:club-available-students'),
        {'club_id': club.id, 'class_group': class_group.id},
    )

    assert response.status_code == 200
    assert response.data['results'] == []
