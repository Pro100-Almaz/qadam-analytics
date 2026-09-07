"""
GET /api/v1/subject-schedules/?class_group=<id>&include_minor_groups=true

The timetable of a class, optionally widened with the timetables of the
подгруппы bound to it.
"""

import pytest
from django.urls import reverse

from apps.home.models import ClassGroup, ClassGroupCollection
from core.factories import (
    AdminUserFactory, ClassGroupFactory, MinorClassGroupFactory, SubjectFactory,
    SubjectOfferingFactory, SubjectScheduleFactory,
)


SCHEDULES_URL = reverse('lesson-api:subject-schedule-list-create')


@pytest.fixture
def admin_api_client(db, authenticated_client):
    return authenticated_client(AdminUserFactory())


@pytest.fixture
def major_a(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='A')


@pytest.fixture
def english(academic_year, major_a):
    """A подгруппа of 7A, with a schedule of its own."""
    group = MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')
    ClassGroupCollection.bind_minor_groups(major_a, [group])
    return group


def schedule_for(class_group, subject_name, quarter=1):
    offering = SubjectOfferingFactory(
        subject=SubjectFactory(name=subject_name), class_group=class_group,
    )
    return SubjectScheduleFactory(offering=offering, quarter=quarter)


def returned_ids(response):
    return {row['id'] for row in response.data['results']}


def test_without_the_flag_only_the_class_schedules_come_back(admin_api_client, major_a, english):
    own = schedule_for(major_a, 'Математика')
    schedule_for(english, 'English')

    response = admin_api_client.get(SCHEDULES_URL, {'class_group': major_a.id})

    assert response.status_code == 200
    assert returned_ids(response) == {own.id}


def test_the_flag_adds_the_subgroup_schedules(admin_api_client, major_a, english):
    own = schedule_for(major_a, 'Математика')
    subgroup_schedule = schedule_for(english, 'English')

    response = admin_api_client.get(
        SCHEDULES_URL, {'class_group': major_a.id, 'include_minor_groups': 'true'},
    )

    assert returned_ids(response) == {own.id, subgroup_schedule.id}


def test_subgroups_of_another_class_stay_out(admin_api_client, major_a, english, academic_year):
    own = schedule_for(major_a, 'Математика')
    subgroup_schedule = schedule_for(english, 'English')

    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')
    other_subgroup = MinorClassGroupFactory(academic_year=academic_year, letter='Шахматы')
    ClassGroupCollection.bind_minor_groups(other_class, [other_subgroup])
    schedule_for(other_class, 'Физика')
    schedule_for(other_subgroup, 'Шахматы')

    response = admin_api_client.get(
        SCHEDULES_URL, {'class_group': major_a.id, 'include_minor_groups': 'true'},
    )

    assert returned_ids(response) == {own.id, subgroup_schedule.id}


def test_a_shared_subgroup_shows_up_for_both_classes(
    admin_api_client, major_a, english, academic_year
):
    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')
    ClassGroupCollection.bind_minor_groups(other_class, [english])
    subgroup_schedule = schedule_for(english, 'English')

    for class_group in (major_a, other_class):
        response = admin_api_client.get(
            SCHEDULES_URL,
            {'class_group': class_group.id, 'include_minor_groups': 'true'},
        )
        assert subgroup_schedule.id in returned_ids(response)


def test_the_flag_on_its_own_changes_nothing(admin_api_client, major_a, english):
    own = schedule_for(major_a, 'Математика')
    subgroup_schedule = schedule_for(english, 'English')

    response = admin_api_client.get(SCHEDULES_URL, {'include_minor_groups': 'true'})

    assert returned_ids(response) == {own.id, subgroup_schedule.id}


def test_rows_name_their_class_group_so_subgroups_are_distinguishable(
    admin_api_client, major_a, english
):
    schedule_for(major_a, 'Математика')
    schedule_for(english, 'English')

    response = admin_api_client.get(
        SCHEDULES_URL, {'class_group': major_a.id, 'include_minor_groups': 'true'},
    )

    by_category = {
        row['class_group']['category']: row['class_group']['id']
        for row in response.data['results']
    }
    assert by_category == {
        ClassGroup.MAJOR_CHOICE: major_a.id,
        ClassGroup.MINOR_CHOICE: english.id,
    }


def test_a_free_entry_of_the_class_is_matched_by_its_own_class_group(admin_api_client, major_a):
    free_entry = SubjectScheduleFactory(
        offering=None, class_group=major_a, description='Классный час', quarter=1,
    )

    response = admin_api_client.get(SCHEDULES_URL, {'class_group': major_a.id})

    assert free_entry.id in returned_ids(response)
    row = next(r for r in response.data['results'] if r['id'] == free_entry.id)
    assert row['type'] == 'other'
    assert row['class_group_id'] == major_a.id


def test_rows_predating_the_class_group_field_are_still_matched(admin_api_client, major_a):
    offering = SubjectOfferingFactory(
        subject=SubjectFactory(name='Математика'), class_group=major_a,
    )
    legacy = SubjectScheduleFactory(offering=offering, class_group=None, quarter=1)

    response = admin_api_client.get(SCHEDULES_URL, {'class_group': major_a.id})

    assert returned_ids(response) == {legacy.id}
    row = response.data['results'][0]
    assert row['class_group_id'] == major_a.id


def test_other_filters_still_apply(admin_api_client, major_a, english):
    schedule_for(major_a, 'Математика', quarter=1)
    q2_subgroup = schedule_for(english, 'English', quarter=2)

    response = admin_api_client.get(SCHEDULES_URL, {
        'class_group': major_a.id, 'include_minor_groups': 'true', 'quarter': 2,
    })

    assert returned_ids(response) == {q2_subgroup.id}


def test_a_non_numeric_class_group_is_a_400(admin_api_client):
    response = admin_api_client.get(SCHEDULES_URL, {'class_group': 'abc'})

    assert response.status_code == 400
    assert 'class_group' in response.data['detail']
