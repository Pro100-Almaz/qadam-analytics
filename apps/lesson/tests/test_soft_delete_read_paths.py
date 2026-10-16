"""Spec 0013, AC-10 — lesson-side read paths leave soft-deleted children out.

A default manager hides a deleted row when it is queried directly. It does
not when a query starts at a live parent and joins into the child
(`filter(child__…)`, `Count('child')`), so every such site in the read-path
audit got an explicit `is_deleted=False` and a test here. Each test sets up a
live parent with one deleted child and checks the child is not counted.
"""

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group
from django.test import RequestFactory

from apps.home.models import HomeroomTeacherAssignment
from apps.home.repo.students import calculate_quarter_grade
from apps.lesson.api.attendance_views import apply_schedule_filters
from apps.lesson.api.homework import grade_queryset as homework_grade_queryset
from apps.lesson.api.serializers import (
    GradingDataSerializer, LessonDetailSerializer, LessonListSerializer,
)
from apps.lesson.models import Homework, SubjectSchedule
from apps.lesson.services import build_graded_percent_map
from core.factories import (
    AdminUserFactory, ClassGroupFactory, EnrollmentFactory,
    HomeworkGradeFactory, LessonFactory, SubjectOfferingFactory,
    SubjectScheduleFactory, TeacherFactory, TeachingAssignmentFactory,
    TopicFactory, TopicGradeFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def graded_lesson():
    """A lesson with one enrolled student, whose only grade is deleted."""
    offering = SubjectOfferingFactory()
    enrollment = EnrollmentFactory(class_group=offering.class_group)
    lesson = LessonFactory(offering=offering, quarter=1)
    topic = TopicFactory(lesson=lesson, weight=100)
    grade = TopicGradeFactory(topic=topic, student=enrollment.student, grade=80)
    grade.delete()
    return lesson, enrollment.student


@pytest.fixture
def unenrolled_lesson():
    """A lesson whose class has one student, whose enrollment is deleted."""
    offering = SubjectOfferingFactory()
    enrollment = EnrollmentFactory(class_group=offering.class_group)
    enrollment.delete()
    return LessonFactory(offering=offering), enrollment.student


def test_ac10_quarter_average_excludes_deleted_grade(graded_lesson):
    lesson, student = graded_lesson
    assert calculate_quarter_grade(1, lesson.offering, student) == 0


def test_ac10_graded_percent_map_excludes_deleted_grade(graded_lesson):
    lesson, _ = graded_lesson
    assert build_graded_percent_map([lesson]) == {lesson.id: 0}


def test_ac10_lesson_list_graded_percent_excludes_deleted_grade(graded_lesson):
    lesson, _ = graded_lesson
    assert LessonListSerializer(context={}).get_graded_percent(lesson) == 0


def test_ac10_lesson_detail_students_exclude_deleted_enrollment(unenrolled_lesson):
    lesson, _ = unenrolled_lesson
    serializer = LessonDetailSerializer()
    assert serializer.get_students(lesson) == []
    assert serializer.get_student_grades(lesson) == {}


def test_ac10_grading_data_students_exclude_deleted_enrollment(unenrolled_lesson):
    lesson, _ = unenrolled_lesson
    assert GradingDataSerializer()._get_students(lesson) == []


def test_ac10_schedule_teacher_filter_excludes_deleted_teaching_assignment():
    assignment = TeachingAssignmentFactory()
    SubjectScheduleFactory(offering=assignment.offering)
    assignment.delete()

    schedules, error = apply_schedule_filters(
        SubjectSchedule.objects.all(), {'teacher': str(assignment.teacher_id)},
    )

    assert error is None
    assert not schedules.exists()


def test_ac10_homework_homeroom_grades_exclude_deleted_enrollment():
    teacher = TeacherFactory()
    teacher.user.groups.add(Group.objects.get_or_create(name='HomeroomTeacher')[0])
    class_group = ClassGroupFactory()
    HomeroomTeacherAssignment.objects.create(teacher=teacher, class_group=class_group)
    enrollment = EnrollmentFactory(class_group=class_group)
    # A grade in an offering the homeroom teacher does not teach: only the
    # homeroom branch, which joins through the enrollment, can reach it.
    grade = HomeworkGradeFactory(
        student=enrollment.student,
        homework__teaching_assignment__offering=SubjectOfferingFactory(
            class_group=class_group,
        ),
    )
    assert homework_grade_queryset(teacher.user).filter(pk=grade.pk).exists()

    enrollment.delete()

    assert not homework_grade_queryset(teacher.user).filter(pk=grade.pk).exists()


def test_ac10_homework_admin_grade_count_excludes_deleted_grade():
    live, deleted = HomeworkGradeFactory.create_batch(2)
    deleted.homework = live.homework
    deleted.save()
    deleted.delete()

    request = RequestFactory().get('/admin/lesson/homework/')
    request.user = AdminUserFactory(is_superuser=True, is_staff=True)
    homework = admin.site._registry[Homework].get_queryset(request).get(
        pk=live.homework_id,
    )

    assert homework._grade_count == 1
