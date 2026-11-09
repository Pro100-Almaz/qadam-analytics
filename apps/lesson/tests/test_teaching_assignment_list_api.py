"""
`quarter` filter on the teaching-assignment list.

The list returns one row per offering quarter, so without the filter a class
group's request carries all four quarters of every subject.
"""

import pytest
from django.urls import reverse

from core.factories import (
    ClassGroupFactory, SubjectOfferingFactory, TeachingAssignmentFactory,
)


URL = reverse('lesson-api:teaching-assignment-list')


@pytest.fixture
def offering(academic_year):
    offering = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    )
    for quarter in (1, 2, 3, 4):
        TeachingAssignmentFactory(offering=offering, quarter=quarter)
    return offering


def test_quarter_filter_returns_only_that_quarter(offering, authenticated_client, admin_user):
    response = authenticated_client(admin_user).get(URL, {
        'academic_year': offering.class_group.academic_year_id,
        'class_group': offering.class_group_id,
        'quarter': 2,
    })

    assert response.status_code == 200
    assert [row['quarter'] for row in response.data['results']] == [2]


def test_without_quarter_returns_every_quarter(offering, authenticated_client, admin_user):
    response = authenticated_client(admin_user).get(URL, {
        'class_group': offering.class_group_id,
    })

    assert response.status_code == 200
    assert [row['quarter'] for row in response.data['results']] == [1, 2, 3, 4]


@pytest.mark.parametrize('quarter', ['5', '0', 'abc'])
def test_invalid_quarter_is_rejected(quarter, authenticated_client, admin_user):
    response = authenticated_client(admin_user).get(URL, {'quarter': quarter})

    assert response.status_code == 400
