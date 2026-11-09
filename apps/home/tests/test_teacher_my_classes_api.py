"""
`quarter` filter on teacher/my-classes/.

Assignments are per quarter, so without the filter a teacher who teaches a
class only in Q1 still sees it listed when the frontend asks for Q2.
"""

import pytest
from django.urls import reverse

from core.factories import (
    ClassGroupFactory, SubjectOfferingFactory, TeachingAssignmentFactory,
)


URL = reverse('home-api:teacher-my-classes')


@pytest.fixture
def classes(teacher, academic_year):
    q1_offering = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year, letter='A'),
    )
    q2_offering = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year, letter='B'),
    )
    TeachingAssignmentFactory(teacher=teacher, offering=q1_offering, quarter=1)
    TeachingAssignmentFactory(teacher=teacher, offering=q2_offering, quarter=2)
    return q1_offering.class_group, q2_offering.class_group


def test_quarter_filter_returns_only_that_quarters_classes(classes, teacher, authenticated_client):
    q1_class, _ = classes

    response = authenticated_client(teacher.user).get(URL, {'quarter': 1})

    assert response.status_code == 200
    assert [row['class_group_id'] for row in response.data] == [q1_class.id]


def test_without_quarter_returns_every_quarters_classes(classes, teacher, authenticated_client):
    response = authenticated_client(teacher.user).get(URL)

    assert response.status_code == 200
    assert {row['class_group_id'] for row in response.data} == {c.id for c in classes}


@pytest.mark.parametrize('quarter', ['5', '0', 'abc'])
def test_invalid_quarter_is_rejected(quarter, teacher, authenticated_client):
    response = authenticated_client(teacher.user).get(URL, {'quarter': quarter})

    assert response.status_code == 400
