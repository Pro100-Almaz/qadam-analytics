"""
`can_edit` on subject schedules.

The frontend's attendance sheet and schedule builder are read-only unless the
schedule says `can_edit: true`. The flag follows the rule the write endpoints
enforce: the offering's teacher for that quarter, or the homeroom teacher of
the offering's class, may edit; nobody else below an admin role may.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from apps.home.models import HomeroomTeacherAssignment
from apps.lesson.api.serializers import SubjectScheduleSerializer
from core.factories import (
    ClassGroupFactory, ScheduleSessionFactory, SubjectOfferingFactory,
    SubjectScheduleFactory, TeacherFactory, TeachingAssignmentFactory,
)


SCHEDULES_URL = reverse('lesson-api:subject-schedule-list-create')


@pytest.fixture
def schedule(academic_year):
    class_group = ClassGroupFactory(academic_year=academic_year)
    offering = SubjectOfferingFactory(class_group=class_group)
    schedule = SubjectScheduleFactory(offering=offering, quarter=1)
    ScheduleSessionFactory(schedule=schedule, weekday=0)
    return schedule


def can_edit_for(user, schedule):
    request = APIRequestFactory().get(SCHEDULES_URL)
    request.user = user
    return SubjectScheduleSerializer(
        schedule, context={'request': request},
    ).data['can_edit']


def test_offering_teacher_can_edit_schedule(schedule):
    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=schedule.offering, quarter=1)

    assert can_edit_for(teacher.user, schedule) is True


def test_homeroom_teacher_can_edit_schedule(schedule):
    homeroom = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(
        teacher=homeroom, class_group=schedule.offering.class_group,
    )

    assert can_edit_for(homeroom.user, schedule) is True


def test_teacher_of_another_offering_cannot_edit_schedule(schedule):
    teacher = TeacherFactory()
    TeachingAssignmentFactory(
        teacher=teacher,
        offering=SubjectOfferingFactory(class_group=schedule.offering.class_group),
        quarter=1,
    )

    assert can_edit_for(teacher.user, schedule) is False


def test_admin_can_edit_schedule(schedule, admin_user):
    assert can_edit_for(admin_user, schedule) is True


def test_can_edit_is_false_without_request(schedule):
    assert SubjectScheduleSerializer(schedule).data['can_edit'] is False


def test_schedule_list_reports_can_edit(schedule, authenticated_client):
    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=schedule.offering, quarter=1)

    response = authenticated_client(teacher.user).get(SCHEDULES_URL)

    rows = {row['id']: row for row in response.data['results']}
    assert rows[schedule.id]['can_edit'] is True
