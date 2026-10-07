"""
A student's own subject list takes its grades from the quarter marks teachers
entered (`QuarterGrade`, spec 0008), not from marks derived from topic grades.
"""

import pytest
from django.urls import reverse

from apps.home.models import QuarterGrade
from apps.lesson.models import Lesson
from core.factories import (
    ClassGroupFactory, EnrollmentFactory, SubjectOfferingFactory,
)


@pytest.fixture
def enrolled(academic_year):
    class_group = ClassGroupFactory(academic_year=academic_year)
    student = EnrollmentFactory(class_group=class_group).student
    maths = SubjectOfferingFactory(class_group=class_group)
    physics = SubjectOfferingFactory(class_group=class_group)
    return student, maths, physics


def my_subjects(authenticated_client, student):
    response = authenticated_client(student.user).get(reverse('home-api:student-my-subjects'))
    assert response.status_code == 200
    return {row['offering_id']: row for row in response.data}


def test_grades_come_from_teacher_entered_quarter_grades(enrolled, authenticated_client):
    student, maths, physics = enrolled
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=student, offering=maths, quarter=2, grade=4)
    QuarterGrade.objects.create(student=student, offering=physics, quarter=3, grade=3)

    rows = my_subjects(authenticated_client, student)

    assert rows[maths.id]['quarter_grades'] == {'1': 5, '2': 4, '3': None, '4': None}
    assert rows[maths.id]['student_grade'] == 4.5
    assert rows[physics.id]['quarter_grades'] == {'1': None, '2': None, '3': 3, '4': None}
    assert rows[physics.id]['student_grade'] == 3.0


def test_lessons_without_a_quarter_mark_give_no_grade(enrolled, authenticated_client):
    student, maths, _ = enrolled
    Lesson.objects.create(offering=maths, quarter=1, title='Algebra')

    rows = my_subjects(authenticated_client, student)

    assert rows[maths.id]['quarter_grades'] == {'1': None, '2': None, '3': None, '4': None}
    assert rows[maths.id]['student_grade'] == 0


def test_grades_outside_current_class_are_ignored(enrolled, authenticated_client, academic_year):
    student, maths, _ = enrolled
    elsewhere = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    )
    QuarterGrade.objects.create(student=student, offering=elsewhere, quarter=1, grade=5)

    rows = my_subjects(authenticated_client, student)

    assert elsewhere.id not in rows
    assert rows[maths.id]['quarter_grades']['1'] is None
