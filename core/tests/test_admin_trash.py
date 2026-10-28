"""Spec 0014 — the admin side of soft deletion: AC-9 (admin half) and AC-11."""

import re

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.home.models import Subject, SubjectOffering
from apps.lesson.models import Lesson, TopicGrade
from core.admin_mixins import SoftDeleteAdminMixin
from core.admin_trash import legacy_batch_id
from core.factories import (
    LessonFactory, SchoolFactory, SubjectFactory, SubjectOfferingFactory,
    TopicGradeFactory, UserFactory,
)
from core.soft_delete import soft_delete_models
from core.tenancy import school_scope

pytestmark = pytest.mark.django_db

PASSWORD = 'testpass123'


@pytest.fixture(autouse=True)
def _enforce(settings):
    # The scoping assertions below mean nothing with the filter switched off;
    # see core/tests/test_admin_school_switcher.py.
    settings.SCHOOL_SCOPE_MODE = 'enforce'


@pytest.fixture
def school_a(db):
    return SchoolFactory(slug='trash_a', name='Alpha School')


@pytest.fixture
def school_b(db):
    return SchoolFactory(slug='trash_b', name='Beta School')


def _login(user):
    client = Client()
    client.post(
        reverse('admin:login'),
        {'username': user.username, 'password': PASSWORD, 'next': '/admin/'},
    )
    return client


@pytest.fixture
def root_client(school_a):
    root = UserFactory(school=school_a, username='root', is_superuser=True, is_staff=True)
    return _login(root), root


@pytest.fixture
def staff_client(school_a):
    """Every model permission, but neither superuser nor in the Admin group."""
    staff = UserFactory(school=school_a, username='staffer', is_staff=True)
    staff.user_permissions.add(*Permission.objects.all())
    return _login(staff), staff


def _offering_tree(school):
    with school_scope(school):
        offering = SubjectOfferingFactory(school=school)
        grade = TopicGradeFactory(topic__lesson__offering=offering)
    return offering, grade


# ── AC-9, admin half ─────────────────────────────────────────────────────────

def test_every_admin_of_a_soft_deletable_model_soft_deletes():
    missing = [
        model._meta.label for model in soft_delete_models()
        if model in admin.site._registry
        and not isinstance(admin.site._registry[model], SoftDeleteAdminMixin)
    ]
    assert missing == []


def test_ac9_queryset_and_admin_bulk_delete_are_soft(root_client, school_a):
    client, root = root_client
    with school_scope(school_a):
        subjects = SubjectFactory.create_batch(2, school=school_a)
        offering = SubjectOfferingFactory(school=school_a, subject=subjects[0])
    pks = [s.pk for s in subjects]

    # The confirmation page lists the walker's tree, cascade included.
    confirm = client.post(reverse('admin:home_subject_changelist'), {
        'action': 'delete_selected', '_selected_action': pks,
    })
    assert confirm.status_code == 200
    assert str(offering) in confirm.content.decode()

    response = client.post(reverse('admin:home_subject_changelist'), {
        'action': 'delete_selected', '_selected_action': pks, 'post': 'yes',
    })

    assert response.status_code == 302
    rows = Subject._base_manager.filter(pk__in=pks)
    assert rows.count() == 2
    assert all(r.is_deleted and r.deleted_by_id == root.pk for r in rows)
    offering_row = SubjectOffering._base_manager.get(pk=offering.pk)
    assert offering_row.is_deleted
    assert offering_row.deletion_batch == rows[0].deletion_batch


def test_ac9_admin_single_delete_is_soft(root_client, school_a):
    client, root = root_client
    with school_scope(school_a):
        lesson = LessonFactory(offering=SubjectOfferingFactory(school=school_a))

    response = client.post(
        reverse('admin:lesson_lesson_delete', args=[lesson.pk]), {'post': 'yes'},
    )

    assert response.status_code == 302
    row = Lesson._base_manager.get(pk=lesson.pk)
    assert row.is_deleted and row.deleted_by_id == root.pk


# ── AC-11 ────────────────────────────────────────────────────────────────────

def test_ac11_trash_lists_restores_purges_scoped(
    root_client, staff_client, school_a, school_b,
):
    client, root = root_client
    offering_a, grade_a = _offering_tree(school_a)
    offering_b, _ = _offering_tree(school_b)
    offering_a.delete(user=root)
    offering_b.delete()
    batch_a = SubjectOffering._base_manager.get(pk=offering_a.pk).deletion_batch
    batch_b = SubjectOffering._base_manager.get(pk=offering_b.pk).deletion_batch

    # Listed: the active school's rows only, grouped by batch.
    index = client.get(reverse('admin:trash_index')).content.decode()
    assert 'Subject offerings' in index
    page = client.get(
        reverse('admin:trash_model', args=['home', 'subjectoffering']),
    ).content.decode()
    assert str(batch_a) in page
    assert str(batch_b) not in page
    assert re.search(r'Topic grades 1', page)

    # Another school's batch does not exist from here.
    assert client.post(reverse('admin:trash_restore', args=[batch_b])).status_code == 404
    assert client.get(reverse('admin:trash_purge', args=[batch_b])).status_code == 404

    # Restore brings the whole batch back.
    response = client.post(reverse('admin:trash_restore', args=[batch_a]))
    assert response.status_code == 302
    assert SubjectOffering._base_manager.get(pk=offering_a.pk).is_deleted is False
    assert TopicGrade._base_manager.get(pk=grade_a.pk).is_deleted is False

    # Purge: confirmation first, then gone for good, cascade included.
    offering_a.refresh_from_db()
    offering_a.delete(user=root)
    batch_a = SubjectOffering._base_manager.get(pk=offering_a.pk).deletion_batch
    confirm = client.get(reverse('admin:trash_purge', args=[batch_a]))
    assert confirm.status_code == 200
    assert SubjectOffering._base_manager.filter(pk=offering_a.pk).exists()

    staff, _ = staff_client
    forbidden = staff.post(reverse('admin:trash_purge', args=[batch_a]))
    assert forbidden.status_code == 403
    assert SubjectOffering._base_manager.filter(pk=offering_a.pk).exists()

    response = client.post(reverse('admin:trash_purge', args=[batch_a]))
    assert response.status_code == 302
    assert not SubjectOffering._base_manager.filter(pk=offering_a.pk).exists()
    assert not TopicGrade._base_manager.filter(pk=grade_a.pk).exists()


def test_ac11_staff_without_admin_group_may_restore(staff_client, school_a):
    client, staff = staff_client
    offering, _ = _offering_tree(school_a)
    offering.delete()
    batch = SubjectOffering._base_manager.get(pk=offering.pk).deletion_batch

    assert client.post(reverse('admin:trash_restore', args=[batch])).status_code == 302
    assert not SubjectOffering._base_manager.get(pk=offering.pk).is_deleted


def test_ac11_restore_guard_failure_is_an_admin_message(root_client, school_a):
    client, _ = root_client
    with school_scope(school_a):
        lesson = LessonFactory(offering=SubjectOfferingFactory(school=school_a))
        grade = TopicGradeFactory(topic__lesson=lesson)
    grade.delete()
    lesson.delete()
    batch = TopicGrade._base_manager.get(pk=grade.pk).deletion_batch

    response = client.post(reverse('admin:trash_restore', args=[batch]), follow=True)

    assert response.status_code == 200
    assert 'Cannot restore' in response.content.decode()
    assert TopicGrade._base_manager.get(pk=grade.pk).is_deleted


def test_ac11_row_deleted_before_batches_is_its_own_batch(root_client, school_a):
    client, _ = root_client
    with school_scope(school_a):
        lesson = LessonFactory(offering=SubjectOfferingFactory(school=school_a))
    lesson.delete()
    Lesson._base_manager.filter(pk=lesson.pk).update(deletion_batch=None)
    batch = legacy_batch_id(Lesson, lesson.pk)

    page = client.get(reverse('admin:trash_model', args=['lesson', 'lesson'])).content.decode()
    assert str(batch) in page

    client.post(reverse('admin:trash_restore', args=[batch]))
    assert not Lesson._base_manager.get(pk=lesson.pk).is_deleted
