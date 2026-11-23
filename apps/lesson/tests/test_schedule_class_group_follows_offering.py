"""
Spec 0018 — an offering-bound SubjectSchedule's class group is always its
offering's: on every write path, and for the rows that existed before.
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

from apps.lesson.models import SubjectSchedule
from core.factories import (
    AdminUserFactory, ClassGroupFactory, MinorClassGroupFactory,
    SubjectOfferingFactory, SubjectScheduleFactory,
)

SCHEDULES_URL = reverse('lesson-api:subject-schedule-list-create')

migration = importlib.import_module(
    'apps.lesson.migrations.0035_schedule_class_group_from_offering'
)


def detail_url(schedule):
    return reverse('lesson-api:subject-schedule-detail', args=[schedule.id])


@pytest.fixture
def admin_api_client(db, authenticated_client):
    return authenticated_client(AdminUserFactory())


@pytest.fixture
def major(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='A')


@pytest.fixture
def subgroup(academic_year):
    return MinorClassGroupFactory(academic_year=academic_year, letter='Music A')


@pytest.fixture
def offering(major):
    return SubjectOfferingFactory(class_group=major)


def force_class_group(schedule, class_group):
    """Store a class group past `save()`, the way drifted rows came to be."""
    SubjectSchedule.unscoped.filter(pk=schedule.pk).update(class_group=class_group)


def stored_class_group_id(schedule):
    return SubjectSchedule.unscoped.values_list(
        'class_group_id', flat=True,
    ).get(pk=schedule.pk)


def test_ac1_migration_aligns_class_group_with_offering(offering, major, subgroup):
    drifted = SubjectScheduleFactory(offering=offering, quarter=1)
    legacy = SubjectScheduleFactory(offering=offering, quarter=2)
    deleted = SubjectScheduleFactory(offering=offering, quarter=3)
    aligned = SubjectScheduleFactory(offering=offering, quarter=4)
    free_entry = SubjectScheduleFactory(
        offering=None, class_group=subgroup, description='Break', quarter=1,
    )
    force_class_group(drifted, subgroup)
    force_class_group(legacy, None)
    force_class_group(deleted, subgroup)
    deleted.delete()

    migration.align_with_offering(django_apps, None)

    for schedule in (drifted, legacy, deleted, aligned):
        assert stored_class_group_id(schedule) == major.id
    assert stored_class_group_id(free_entry) == subgroup.id


def test_ac2_post_takes_offering_class_group_over_sent_one(
    admin_api_client, offering, major, subgroup,
):
    response = admin_api_client.post(SCHEDULES_URL, {
        'offering': offering.id, 'class_group': subgroup.id, 'quarter': 1,
    }, format='json')

    assert response.status_code == 201, response.data
    assert response.data['class_group_id'] == major.id
    assert stored_class_group_id(SubjectSchedule.objects.get(pk=response.data['id'])) == major.id


def test_ac3_post_without_class_group_takes_offering_class_group(
    admin_api_client, offering, major,
):
    response = admin_api_client.post(SCHEDULES_URL, {
        'offering': offering.id, 'quarter': 1,
    }, format='json')

    assert response.status_code == 201, response.data
    assert stored_class_group_id(SubjectSchedule.objects.get(pk=response.data['id'])) == major.id


def test_ac4_patch_class_group_alone_keeps_offering_class_group(
    admin_api_client, offering, major, subgroup,
):
    schedule = SubjectScheduleFactory(offering=offering)

    response = admin_api_client.patch(
        detail_url(schedule), {'class_group': subgroup.id}, format='json',
    )

    assert response.status_code == 200, response.data
    assert response.data['class_group_id'] == major.id
    assert stored_class_group_id(schedule) == major.id


@pytest.mark.parametrize('send_class_group', [False, True])
def test_ac5_patch_to_other_offering_follows_new_offering(
    admin_api_client, offering, subgroup, academic_year, send_class_group,
):
    schedule = SubjectScheduleFactory(offering=offering)
    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')
    target = SubjectOfferingFactory(class_group=other_class)
    payload = {'offering': target.id}
    if send_class_group:
        payload['class_group'] = subgroup.id

    response = admin_api_client.patch(detail_url(schedule), payload, format='json')

    assert response.status_code == 200, response.data
    assert stored_class_group_id(schedule) == other_class.id


def test_ac6_patch_offering_to_null_keeps_class_group_and_needs_description(
    admin_api_client, offering, major, subgroup,
):
    kept = SubjectScheduleFactory(offering=offering, quarter=1)
    sent = SubjectScheduleFactory(offering=offering, quarter=2)
    undescribed = SubjectScheduleFactory(offering=offering, quarter=3)

    response = admin_api_client.patch(
        detail_url(kept), {'offering': None, 'description': 'Assembly'}, format='json',
    )
    assert response.status_code == 200, response.data
    assert stored_class_group_id(kept) == major.id

    response = admin_api_client.patch(detail_url(sent), {
        'offering': None, 'description': 'Assembly', 'class_group': subgroup.id,
    }, format='json')
    assert response.status_code == 200, response.data
    assert stored_class_group_id(sent) == subgroup.id

    response = admin_api_client.patch(
        detail_url(undescribed), {'offering': None}, format='json',
    )
    assert response.status_code == 400
    assert 'description' in response.data


def test_ac7_offering_class_group_change_cascades_to_schedules(
    offering, academic_year,
):
    live = SubjectScheduleFactory(offering=offering, quarter=1)
    deleted = SubjectScheduleFactory(offering=offering, quarter=2)
    deleted.delete()
    new_class = ClassGroupFactory(academic_year=academic_year, letter='C')

    offering.class_group = new_class
    offering.save()

    assert stored_class_group_id(live) == new_class.id
    assert stored_class_group_id(deleted) == new_class.id


def test_ac8_orm_save_takes_offering_class_group(offering, major, subgroup):
    schedule = SubjectSchedule(offering=offering, class_group=subgroup, quarter=1)
    schedule.save()
    assert stored_class_group_id(schedule) == major.id

    schedule.class_group = subgroup
    schedule.quarter = 2
    schedule.save(update_fields=['quarter'])
    assert stored_class_group_id(schedule) == major.id
