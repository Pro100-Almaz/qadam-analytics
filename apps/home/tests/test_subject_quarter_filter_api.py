"""
`quarter` filter on subjects/<pk>/ and my-subjects/.

Assignments and lessons are per quarter, so without the filter both
endpoints answer for the whole year whatever quarter the frontend shows.
"""

import pytest
from django.urls import reverse

from core.factories import (
    ClassGroupFactory, LessonFactory, SubjectFactory, SubjectOfferingFactory,
    TeacherFactory, TeachingAssignmentFactory,
)


def detail_url(subject):
    return reverse('home-api:subject-detail', args=[subject.pk])


MY_SUBJECTS_URL = reverse('home-api:my-subjects')


# ── subjects/<pk>/ ──

@pytest.fixture
def offering(academic_year):
    offering = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    )
    LessonFactory(offering=offering, quarter=1)
    LessonFactory(offering=offering, quarter=2)
    LessonFactory(offering=offering, quarter=2)
    return offering


def test_subject_detail_quarter_counts_only_that_quarters_lessons(
    offering, authenticated_client, admin_user,
):
    client = authenticated_client(admin_user)

    whole_year = client.get(detail_url(offering.subject))
    second = client.get(detail_url(offering.subject), {'quarter': 2})

    assert whole_year.data['lessons_count'] == 3
    assert second.data['lessons_count'] == 2


def test_subject_detail_quarter_picks_that_quarters_primary_teacher(
    offering, authenticated_client, admin_user,
):
    q1_teacher, q2_teacher = TeacherFactory(), TeacherFactory()
    TeachingAssignmentFactory(teacher=q1_teacher, offering=offering, quarter=1)
    TeachingAssignmentFactory(teacher=q2_teacher, offering=offering, quarter=2)
    client = authenticated_client(admin_user)

    first = client.get(detail_url(offering.subject), {'quarter': 1})
    third = client.get(detail_url(offering.subject), {'quarter': 3})

    assert first.data['primary_teacher']['id'] == q1_teacher.id
    assert third.data['primary_teacher'] is None


@pytest.mark.parametrize('quarter', ['5', '0', 'abc'])
def test_subject_detail_invalid_quarter_is_rejected(
    quarter, offering, authenticated_client, admin_user,
):
    response = authenticated_client(admin_user).get(
        detail_url(offering.subject), {'quarter': quarter},
    )

    assert response.status_code == 400


# ── my-subjects/ ──

@pytest.fixture
def subjects(teacher):
    q1_subject = SubjectFactory(name='Algebra')
    q2_subject = SubjectFactory(name='Geometry')
    TeachingAssignmentFactory(
        teacher=teacher, quarter=1,
        offering=SubjectOfferingFactory(subject=q1_subject),
    )
    TeachingAssignmentFactory(
        teacher=teacher, quarter=2,
        offering=SubjectOfferingFactory(subject=q2_subject),
    )
    return q1_subject, q2_subject


def test_my_subjects_quarter_returns_only_that_quarters_subjects(
    subjects, teacher, authenticated_client,
):
    q1_subject, _ = subjects

    response = authenticated_client(teacher.user).get(MY_SUBJECTS_URL, {'quarter': 1})

    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [q1_subject.id]


def test_my_subjects_without_quarter_returns_every_quarters_subjects(
    subjects, teacher, authenticated_client,
):
    response = authenticated_client(teacher.user).get(MY_SUBJECTS_URL)

    assert response.status_code == 200
    assert {row['id'] for row in response.data['results']} == {s.id for s in subjects}


@pytest.mark.parametrize('quarter', ['5', '0', 'abc'])
def test_my_subjects_invalid_quarter_is_rejected(quarter, teacher, authenticated_client):
    response = authenticated_client(teacher.user).get(MY_SUBJECTS_URL, {'quarter': quarter})

    assert response.status_code == 400
