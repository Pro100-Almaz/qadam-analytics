"""Spec 0014 — the soft-delete mechanism itself: AC-1, AC-9, AC-13."""

import pytest
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from apps.authentication.models import CustomUser, Student
from apps.home.models import Subject, SubjectOffering
from apps.lesson.models import QuarterGradeSnapshot
from core.factories import (
    AdminUserFactory, StudentFactory, SubjectFactory, SubjectOfferingFactory,
)
from core.soft_delete import soft_delete_models
from core.tests.soft_delete_builders import BUILDERS

pytestmark = pytest.mark.django_db


def test_registry_has_a_builder_for_every_model():
    assert {m._meta.label for m in soft_delete_models()} == set(BUILDERS)


@pytest.mark.parametrize('label', sorted(BUILDERS))
def test_ac1_delete_sets_is_deleted_and_hides_row(label):
    obj = BUILDERS[label]()
    model = type(obj)._meta.concrete_model
    user = AdminUserFactory()

    obj.delete(user=user)

    row = model._base_manager.get(pk=obj.pk)
    assert row.is_deleted is True
    assert row.deleted_at is not None
    assert row.deletion_batch is not None
    assert row.deleted_by_id == user.pk
    assert not model.objects.filter(pk=obj.pk).exists()
    assert model.all_objects.filter(pk=obj.pk).exists()


def test_ac1_deleted_user_is_hidden_from_in_school_too():
    user = StudentFactory().user
    user.delete()
    assert not CustomUser.objects.filter(pk=user.pk).exists()
    assert not CustomUser.in_school.filter(pk=user.pk).exists()
    assert CustomUser.all_objects.filter(pk=user.pk).exists()


def test_ac9_queryset_and_admin_bulk_delete_are_soft():
    # The admin half of AC-9 is in core/tests/test_admin_trash.py.
    admin = AdminUserFactory()
    subjects = SubjectFactory.create_batch(2)
    offering = SubjectOfferingFactory(subject=subjects[0])

    Subject.objects.filter(pk__in=[s.pk for s in subjects]).delete(user=admin)

    rows = Subject._base_manager.filter(pk__in=[s.pk for s in subjects])
    assert rows.count() == 2
    assert all(r.is_deleted and r.deleted_by_id == admin.pk for r in rows)
    assert len({r.deletion_batch for r in rows}) == 1
    # And the cascade is part of the same batch.
    offering_row = SubjectOffering._base_manager.get(pk=offering.pk)
    assert offering_row.is_deleted
    assert offering_row.deletion_batch == rows[0].deletion_batch


def test_ac9_api_delete_records_the_acting_user(authenticated_client):
    admin = AdminUserFactory()
    subject = SubjectFactory()

    response = authenticated_client(admin).delete(
        reverse('home-api:subject-delete', args=[subject.pk]),
    )

    assert response.status_code == 204
    row = Subject._base_manager.get(pk=subject.pk)
    assert row.is_deleted and row.deleted_by_id == admin.pk


def test_ac9_reverse_relation_delete_is_soft():
    offering = SubjectOfferingFactory()
    subject = offering.subject

    subject.offerings.all().delete()

    assert SubjectOffering._base_manager.get(pk=offering.pk).is_deleted


def _snapshot(student, offering, frozen_by):
    return QuarterGradeSnapshot.objects.create(
        student=student, offering=offering, quarter=1,
        final_grade=80, percentage=80, lesson_count=1, graded_lesson_count=1,
        frozen_by=frozen_by,
    )


def test_ac13_protect_dependent_blocks_soft_delete():
    admin = AdminUserFactory()
    student = StudentFactory()
    offering = SubjectOfferingFactory()
    _snapshot(student, offering, admin)

    for obj in (student, student.user, offering, offering.subject, admin):
        with pytest.raises(ProtectedError):
            obj.delete()

    assert not Student._base_manager.get(pk=student.pk).is_deleted
    assert not CustomUser._base_manager.get(pk=student.user_id).is_deleted
    assert not SubjectOffering._base_manager.get(pk=offering.pk).is_deleted
    assert not CustomUser._base_manager.get(pk=admin.pk).is_deleted
