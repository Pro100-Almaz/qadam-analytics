"""
Spec 0007 — a homework assignment is deleted through its Homework only.

AC-1 … AC-5. Supersedes spec 0005 AC-18, under which deleting the assignment
also deleted the Homework.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.urls import reverse

from apps.home.models import SubjectAssignment, SubjectGrade
from apps.lesson.models import Homework, HomeworkGrade
from apps.lesson.services import attach_files_to_homeworks
from core.factories import (
    EnrollmentFactory, HomeworkFactory, HomeworkGradeFactory, StudentFactory,
    SubjectAssignmentFactory, SubjectGradeFactory, TeacherFactory,
)


def assignment_url(assignment):
    return reverse('home-api:subject-assignment-detail', args=[assignment.pk])


def homework_url(homework):
    return reverse('lesson-api:homework-detail', args=[homework.pk])


def mirror(homework):
    return SubjectAssignment.objects.get(category__code='homework', detail_id=homework.pk)


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


def test_ac1_deleting_a_homework_assignment_via_api_is_a_400(
    teacher, homework, pupil, authenticated_client,
):
    attachment, = attach_files_to_homeworks(
        [homework], [ContentFile(b'%PDF-1.4', name='task.pdf')], teacher.user,
    )
    assignment = mirror(homework)

    response = authenticated_client(teacher.user).delete(assignment_url(assignment))

    assert response.status_code == 400
    assert f'/api/v1/homeworks/{homework.pk}/' in response.data['detail']
    assert SubjectAssignment.objects.filter(pk=assignment.pk).exists()
    assert Homework.objects.filter(pk=homework.pk).exists()
    assert HomeworkGrade.objects.filter(homework=homework, student=pupil).exists()
    assert SubjectGrade.objects.filter(assignment=assignment, student=pupil).exists()
    assert default_storage.exists(attachment.file.name)


def test_ac1_permission_is_checked_before_the_category(homework, authenticated_client):
    outsider = TeacherFactory()

    response = authenticated_client(outsider.user).delete(assignment_url(mirror(homework)))

    assert response.status_code == 403


def test_ac2_model_refuses_to_delete_a_homework_assignment(homework):
    assignment = mirror(homework)

    with pytest.raises(ValidationError):
        assignment.delete()

    assert SubjectAssignment.objects.filter(pk=assignment.pk).exists()
    assert Homework.objects.filter(pk=homework.pk).exists()


def test_ac3_deleting_the_homework_still_removes_its_assignment(
    teacher, homework, authenticated_client,
):
    assignment = mirror(homework)

    response = authenticated_client(teacher.user).delete(homework_url(homework))

    assert response.status_code == 204
    assert not SubjectAssignment.objects.filter(pk=assignment.pk).exists()
    assert not SubjectGrade.objects.filter(assignment_id=assignment.pk).exists()


def test_ac4_an_orphaned_homework_assignment_can_still_be_removed(homework):
    assignment = mirror(homework)
    # A raw queryset delete skips Homework.delete(), leaving the mirror orphaned.
    Homework.objects.filter(pk=homework.pk).delete()

    call_command('sync_homework_assignments', '--fix')

    assert not SubjectAssignment.objects.filter(pk=assignment.pk).exists()


def test_ac4_model_delete_of_an_orphan_is_allowed(homework):
    assignment = mirror(homework)
    Homework.objects.filter(pk=homework.pk).delete()

    assignment.delete()

    assert not SubjectAssignment.objects.filter(pk=assignment.pk).exists()


def test_ac5_other_categories_still_delete(teacher, teaching_assignment, pupil, authenticated_client):
    exam = SubjectAssignmentFactory(offering=teaching_assignment.offering, category='exam')
    SubjectGradeFactory(assignment=exam, student=pupil, grade=40)

    response = authenticated_client(teacher.user).delete(assignment_url(exam))

    assert response.status_code == 204
    assert not SubjectAssignment.objects.filter(pk=exam.pk).exists()
    assert not SubjectGrade.objects.filter(assignment_id=exam.pk).exists()
