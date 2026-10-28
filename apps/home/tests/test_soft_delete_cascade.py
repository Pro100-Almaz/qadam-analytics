"""Spec 0014 — cascade, batch restore and its guards: AC-2, AC-3, AC-4, AC-14."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.home.models import QuarterGrade, SubjectAssignment, SubjectOffering
from apps.lesson import homework_sync
from apps.lesson.models import Lesson, Topic, TopicGrade
from core.factories import (
    EnrollmentFactory, HomeworkFactory, HomeworkGradeFactory, LessonFactory,
    ScheduleAttendanceFactory, ScheduleSessionFactory, StudentFactory,
    SubjectAssignmentFactory, SubjectGradeFactory, SubjectScheduleFactory,
    TopicFactory, TopicGradeFactory,
)
from core.soft_delete import batch_rows, soft_delete_models

pytestmark = pytest.mark.django_db


def _deleted_rows():
    """{(label, pk)} of every soft-deleted row, any model."""
    return {
        (model._meta.label, pk)
        for model in soft_delete_models()
        for pk in model._base_manager.filter(is_deleted=True).values_list('pk', flat=True)
    }


@pytest.fixture
def pupil(class_group):
    student = StudentFactory()
    EnrollmentFactory(student=student, class_group=class_group)
    return student


@pytest.fixture
def full_offering(offering, teaching_assignment, pupil):
    """An offering with one of everything that hangs off it."""
    lesson = LessonFactory(offering=offering)
    topic = TopicFactory(lesson=lesson)
    TopicFactory(lesson=lesson, parent=topic, title='Subtopic')
    TopicGradeFactory(topic=topic, student=pupil, grade=80)
    assignment = SubjectAssignmentFactory(offering=offering)
    SubjectGradeFactory(assignment=assignment, student=pupil, grade=70)
    QuarterGrade.objects.create(student=pupil, offering=offering, quarter=1, grade=5)
    homework = HomeworkFactory(teaching_assignment=teaching_assignment)
    HomeworkGradeFactory(homework=homework, student=pupil, grade=9)
    session = ScheduleSessionFactory(schedule=SubjectScheduleFactory(offering=offering))
    ScheduleAttendanceFactory(session=session, student=pupil, date=datetime.date(2026, 9, 7))
    return offering


EXPECTED_IN_OFFERING_BATCH = {
    'home.SubjectOffering': 1,
    'home.TeachingAssignment': 1,
    'home.SubjectAssignment': 2,       # the plain one and the homework mirror
    'home.SubjectGrade': 2,            # one each
    'home.QuarterGrade': 1,
    'lesson.Lesson': 1,
    'lesson.Topic': 2,
    'lesson.TopicGrade': 1,
    'lesson.Homework': 1,
    'lesson.HomeworkGrade': 1,
    'lesson.SubjectSchedule': 1,
    'lesson.ScheduleSession': 1,
    'lesson.ScheduleAttendance': 1,
}


def test_ac2_offering_delete_cascades_one_batch_and_restores(full_offering):
    before = _deleted_rows()

    full_offering.delete()

    batch = SubjectOffering._base_manager.get(pk=full_offering.pk).deletion_batch
    in_batch = batch_rows(batch)
    assert {m._meta.label: len(pks) for m, pks in in_batch.items()} == EXPECTED_IN_OFFERING_BATCH
    deleted_now = _deleted_rows() - before
    assert deleted_now == {
        (model._meta.label, pk) for model, pks in in_batch.items() for pk in pks
    }
    # Live reads see none of it.
    assert not Lesson.objects.filter(offering=full_offering).exists()

    SubjectOffering._base_manager.get(pk=full_offering.pk).restore()

    assert _deleted_rows() == before
    assert Lesson.objects.filter(offering=full_offering).count() == 1
    assert homework_sync.find_drift() == []


def test_ac3_previously_deleted_child_stays_deleted_on_restore(offering):
    kept, dropped = LessonFactory(offering=offering), LessonFactory(offering=offering)
    dropped.delete()
    earlier_batch = Lesson._base_manager.get(pk=dropped.pk).deletion_batch

    offering.delete()
    SubjectOffering._base_manager.get(pk=offering.pk).restore()

    assert Lesson.objects.filter(pk=kept.pk).exists()
    dropped_row = Lesson._base_manager.get(pk=dropped.pk)
    assert dropped_row.is_deleted
    assert dropped_row.deletion_batch == earlier_batch


def test_ac4_restore_child_of_deleted_parent_refused(lesson):
    topic = TopicFactory(lesson=lesson)
    grade = TopicGradeFactory(topic=topic)
    topic.delete()
    lesson.delete()

    with pytest.raises(ValidationError) as excinfo:
        Topic._base_manager.get(pk=topic.pk).restore()

    assert f'{Lesson._meta.verbose_name} #{lesson.pk}' in ' '.join(excinfo.value.messages)
    assert Topic._base_manager.get(pk=topic.pk).is_deleted
    assert TopicGrade._base_manager.get(pk=grade.pk).is_deleted
    assert Lesson._base_manager.get(pk=lesson.pk).is_deleted


def test_ac14_homework_assignment_direct_delete_still_refused(
    teacher, teaching_assignment, authenticated_client,
):
    homework = HomeworkFactory(teaching_assignment=teaching_assignment)
    assignment = homework_sync.mirror_of(homework.pk)

    response = authenticated_client(teacher.user).delete(
        reverse('home-api:subject-assignment-detail', args=[assignment.pk]),
    )

    assert response.status_code == 400
    assert not SubjectAssignment._base_manager.get(pk=assignment.pk).is_deleted
    with pytest.raises(ValidationError):
        assignment.delete()
    assert not SubjectAssignment._base_manager.get(pk=assignment.pk).is_deleted
