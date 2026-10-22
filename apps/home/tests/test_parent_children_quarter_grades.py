"""
A parent's children list takes its grades from the quarter marks teachers
entered (`QuarterGrade`, spec 0008), not from marks derived from topic grades.
A subject without a mark is left out of the average, not counted as 0.
"""

import pytest
from django.urls import reverse

from apps.home.models import QuarterGrade
from apps.lesson.models import Lesson
from core.factories import (
    ClassGroupFactory, EnrollmentFactory, MinorClassGroupFactory, ParentFactory,
    StudentFactory, SubjectOfferingFactory,
)


@pytest.fixture
def enrolled(academic_year):
    class_group = ClassGroupFactory(academic_year=academic_year)
    student = EnrollmentFactory(class_group=class_group).student
    maths = SubjectOfferingFactory(class_group=class_group)
    physics = SubjectOfferingFactory(class_group=class_group)
    parent = ParentFactory()
    parent.students.add(student)
    return parent, student, maths, physics


def children(authenticated_client, parent):
    response = authenticated_client(parent.user).get(reverse('home-api:parent-children'))
    assert response.status_code == 200
    return {row['id']: row for row in response.data}


def test_grades_come_from_teacher_entered_quarter_grades(enrolled, authenticated_client):
    parent, student, maths, physics = enrolled
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=student, offering=physics, quarter=1, grade=4)
    QuarterGrade.objects.create(student=student, offering=maths, quarter=2, grade=3)

    row = children(authenticated_client, parent)[student.id]

    assert row['quarter_grades'] == {'1': 4.5, '2': 3.0, '3': None, '4': None}
    assert row['student_total_grade'] == 3.75


def test_subjects_without_a_mark_are_not_counted_as_zero(enrolled, authenticated_client):
    parent, student, maths, _ = enrolled
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)

    row = children(authenticated_client, parent)[student.id]

    assert row['quarter_grades']['1'] == 5.0
    assert row['student_total_grade'] == 5.0


def test_lessons_without_a_quarter_mark_give_no_grade(enrolled, authenticated_client):
    parent, student, maths, _ = enrolled
    Lesson.objects.create(offering=maths, quarter=1, title='Algebra')

    row = children(authenticated_client, parent)[student.id]

    assert row['quarter_grades'] == {'1': None, '2': None, '3': None, '4': None}
    assert row['student_total_grade'] is None


def test_grades_outside_current_class_are_ignored(enrolled, authenticated_client, academic_year):
    parent, student, maths, _ = enrolled
    elsewhere = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    )
    QuarterGrade.objects.create(student=student, offering=elsewhere, quarter=1, grade=2)
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)

    row = children(authenticated_client, parent)[student.id]

    assert row['quarter_grades']['1'] == 5.0


def test_child_without_enrollment_has_no_grades(authenticated_client, db):
    parent = ParentFactory()
    child = StudentFactory()
    parent.students.add(child)

    row = children(authenticated_client, parent)[child.id]

    assert row['quarter_grades'] == {'1': None, '2': None, '3': None, '4': None}
    assert row['student_total_grade'] is None


def test_minor_group_offerings_are_included(enrolled, authenticated_client, academic_year):
    parent, student, maths, _ = enrolled
    subgroup = MinorClassGroupFactory(academic_year=academic_year)
    EnrollmentFactory(student=student, class_group=subgroup)
    english = SubjectOfferingFactory(class_group=subgroup)
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=student, offering=english, quarter=1, grade=3)
    QuarterGrade.objects.create(student=student, offering=english, quarter=2, grade=4)

    row = children(authenticated_client, parent)[student.id]

    assert row['quarter_grades'] == {'1': 4.0, '2': 4.0, '3': None, '4': None}
    assert row['student_total_grade'] == 4.0


def test_minor_group_counts_without_a_major_class(authenticated_client, academic_year):
    parent = ParentFactory()
    child = StudentFactory()
    parent.students.add(child)
    subgroup = MinorClassGroupFactory(academic_year=academic_year)
    EnrollmentFactory(student=child, class_group=subgroup)
    english = SubjectOfferingFactory(class_group=subgroup)
    QuarterGrade.objects.create(student=child, offering=english, quarter=1, grade=4)

    row = children(authenticated_client, parent)[child.id]

    assert row['class_group_name'] is None
    assert row['quarter_grades']['1'] == 4.0
    assert row['student_total_grade'] == 4.0
