"""Spec 0014 — homework under soft delete: AC-7, AC-8.

Supersedes two parts of spec 0005: deleting a TeachingAssignment no longer
deletes its homework, and a homework's files stay in storage until it is
purged from the trash.
"""

import datetime

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse

from apps.home.models import SubjectAssignment, SubjectGrade, TeachingAssignment
from apps.lesson.models import Homework, HomeworkGrade
from apps.lesson.services import attach_files_to_homeworks
from core.factories import (
    EnrollmentFactory, HomeworkFactory, HomeworkGradeFactory, StudentFactory,
)
from core.soft_delete import purge_batch

pytestmark = pytest.mark.django_db


@pytest.fixture
def pupil(class_group):
    student = StudentFactory()
    EnrollmentFactory(student=student, class_group=class_group)
    return student


@pytest.fixture
def homework(teaching_assignment, pupil):
    homework = HomeworkFactory(
        teaching_assignment=teaching_assignment, due_date=datetime.date(2026, 10, 5),
    )
    HomeworkGradeFactory(homework=homework, student=pupil, grade=7)
    return homework


def _mirror(homework):
    return SubjectAssignment._base_manager.get(
        category__code='homework', detail_id=homework.pk,
    )


def test_ac7_teaching_assignment_delete_keeps_homework(
    teaching_assignment, homework, admin_user, authenticated_client,
    django_capture_on_commit_callbacks,
):
    teaching_assignment.delete()

    assert Homework.objects.filter(pk=homework.pk).exists()
    assert HomeworkGrade.objects.filter(homework=homework).exists()
    assert not _mirror(homework).is_deleted

    batch = TeachingAssignment._base_manager.get(pk=teaching_assignment.pk).deletion_batch
    with django_capture_on_commit_callbacks(execute=True):
        purge_batch(batch)

    homework.refresh_from_db()
    assert not TeachingAssignment._base_manager.filter(pk=teaching_assignment.pk).exists()
    assert homework.teaching_assignment_id is None
    assert not homework.is_deleted

    response = authenticated_client(admin_user).get(
        reverse('lesson-api:homework-detail', args=[homework.pk]),
    )
    assert response.status_code == 200
    assert response.data['teaching_assignment'] is None
    assert response.data['teacher'] is None


def test_ac8_homework_files_kept_until_purge(
    teacher, homework, pupil, django_capture_on_commit_callbacks,
):
    attachment, = attach_files_to_homeworks(
        [homework], [ContentFile(b'%PDF-1.4', name='task.pdf')], teacher.user,
    )
    stored = attachment.file.name
    mirror = _mirror(homework)

    homework.delete(user=teacher.user)

    assert default_storage.exists(stored)
    batch = Homework._base_manager.get(pk=homework.pk).deletion_batch
    mirror.refresh_from_db()
    assert mirror.is_deleted and mirror.deletion_batch == batch
    mirror_grade = SubjectGrade._base_manager.get(assignment=mirror, student=pupil)
    assert mirror_grade.is_deleted and mirror_grade.deletion_batch == batch
    homework_grade = HomeworkGrade._base_manager.get(homework=homework, student=pupil)
    assert homework_grade.is_deleted and homework_grade.deletion_batch == batch

    with django_capture_on_commit_callbacks(execute=True):
        purge_batch(batch)

    assert not default_storage.exists(stored)
    assert not Homework._base_manager.filter(pk=homework.pk).exists()
    assert not SubjectAssignment._base_manager.filter(pk=mirror.pk).exists()
