"""
A student's classmate list takes each classmate's total from the quarter marks
teachers entered (`QuarterGrade`, spec 0008), not from marks derived from topic
grades, and averages them the same way the student detail payload does.
"""

import pytest
from django.urls import reverse

from apps.home.models import QuarterGrade
from apps.lesson.models import Lesson
from core.factories import (
    AdminUserFactory, ClassGroupFactory, EnrollmentFactory, SubjectOfferingFactory,
)


@pytest.fixture
def classroom(academic_year):
    class_group = ClassGroupFactory(academic_year=academic_year)
    viewer = EnrollmentFactory(class_group=class_group).student
    classmate = EnrollmentFactory(class_group=class_group).student
    maths = SubjectOfferingFactory(class_group=class_group)
    physics = SubjectOfferingFactory(class_group=class_group)
    return viewer, classmate, maths, physics


def classmates(authenticated_client, viewer):
    response = authenticated_client(viewer.user).get(reverse('home-api:student-classmates'))
    assert response.status_code == 200
    return {row['id']: row for row in response.data}


def test_total_comes_from_teacher_entered_quarter_grades(classroom, authenticated_client):
    viewer, classmate, maths, physics = classroom
    QuarterGrade.objects.create(student=classmate, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=classmate, offering=physics, quarter=1, grade=4)
    QuarterGrade.objects.create(student=classmate, offering=maths, quarter=2, grade=3)

    rows = classmates(authenticated_client, viewer)

    # Quarter 1 averages to 4.5, quarter 2 to 3.0; ungraded quarters are skipped.
    assert rows[classmate.id]['student_total_grade'] == 3.75


def test_total_matches_the_classmates_profile(classroom, authenticated_client):
    viewer, classmate, maths, physics = classroom
    QuarterGrade.objects.create(student=classmate, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=classmate, offering=physics, quarter=1, grade=2)
    QuarterGrade.objects.create(student=classmate, offering=maths, quarter=3, grade=4)

    listed = classmates(authenticated_client, viewer)[classmate.id]['student_total_grade']
    profile = authenticated_client(AdminUserFactory()).get(
        reverse('home-api:student-detail', args=[classmate.user_id]),
    ).data['student_total_grade']

    assert listed == profile


def test_lessons_without_a_quarter_mark_give_zero(classroom, authenticated_client):
    viewer, classmate, maths, _ = classroom
    Lesson.objects.create(offering=maths, quarter=1, title='Algebra')

    rows = classmates(authenticated_client, viewer)

    assert rows[classmate.id]['student_total_grade'] == 0


def test_grades_outside_current_class_are_ignored(
    classroom, authenticated_client, academic_year,
):
    viewer, classmate, _, _ = classroom
    elsewhere = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    )
    QuarterGrade.objects.create(student=classmate, offering=elsewhere, quarter=1, grade=5)

    rows = classmates(authenticated_client, viewer)

    assert rows[classmate.id]['student_total_grade'] == 0
