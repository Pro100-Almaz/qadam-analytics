"""
Any teacher may GET a student's profile pages — achievements, reading entries,
homework, clubs and reports — for a student they do not teach. Writes on the
same URLs still need can_access_student().
"""

import pytest
from django.urls import reverse
from rest_framework import status

from core.factories import (
    ClubFactory, EnrollmentFactory, HomeworkFactory, SubjectOfferingFactory,
    TeacherFactory, TeachingAssignmentFactory,
)


@pytest.fixture
def stranger(db):
    """A teacher with no link at all to the student."""
    return TeacherFactory()


@pytest.fixture
def enrolled_student(student, class_group):
    EnrollmentFactory(student=student, class_group=class_group)
    return student


@pytest.mark.parametrize('name', [
    'achievement-api:achievement-list-create',
    'achievement-api:reading-entry-list-create',
])
def test_any_teacher_can_list_achievements_and_reading_entries(
    name, enrolled_student, stranger, authenticated_client,
):
    response = authenticated_client(stranger.user).get(
        reverse(name, args=[enrolled_student.pk]),
    )

    assert response.status_code == status.HTTP_200_OK, response.data


def test_any_teacher_can_list_reports(
    enrolled_student, stranger, authenticated_client,
):
    response = authenticated_client(stranger.user).get(
        reverse('student-report-api:report-list', args=[enrolled_student.pk]),
    )

    assert response.status_code == status.HTTP_200_OK, response.data


def test_any_teacher_sees_every_club_of_the_student(
    enrolled_student, stranger, authenticated_client,
):
    club = ClubFactory(status='active')
    club.members.add(enrolled_student)

    response = authenticated_client(stranger.user).get(
        reverse('achievement-api:student-clubs', args=[enrolled_student.pk]),
    )

    assert response.status_code == status.HTTP_200_OK, response.data
    assert [row['id'] for row in response.data['results']] == [club.id]


def test_any_teacher_sees_published_homework_but_not_others_drafts(
    enrolled_student, class_group, stranger, authenticated_client,
):
    published = HomeworkFactory(
        teaching_assignment=TeachingAssignmentFactory(
            offering=SubjectOfferingFactory(class_group=class_group),
        ),
        is_active=True,
    )
    HomeworkFactory(
        teaching_assignment=TeachingAssignmentFactory(
            offering=SubjectOfferingFactory(class_group=class_group),
        ),
        is_active=False,
    )

    response = authenticated_client(stranger.user).get(
        reverse('lesson-api:student-homework-list', args=[enrolled_student.pk]),
    )

    assert response.status_code == status.HTTP_200_OK, response.data
    assert [row['id'] for row in response.data['results']] == [published.id]


def test_any_teacher_still_cannot_create_an_achievement(
    enrolled_student, stranger, authenticated_client,
):
    response = authenticated_client(stranger.user).post(
        reverse(
            'achievement-api:achievement-list-create',
            args=[enrolled_student.pk],
        ),
        {},
        format='json',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_any_teacher_still_cannot_create_a_reading_entry(
    enrolled_student, stranger, authenticated_client,
):
    response = authenticated_client(stranger.user).post(
        reverse(
            'achievement-api:reading-entry-list-create',
            args=[enrolled_student.pk],
        ),
        {},
        format='json',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
