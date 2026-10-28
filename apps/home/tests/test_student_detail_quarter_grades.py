"""
The student detail payload's grade fields come from the quarter marks teachers
entered (`QuarterGrade`, spec 0008), not from marks derived from topic grades.
"""

import pytest
from django.urls import reverse

from apps.home.models import QuarterGrade
from core.factories import (
    AdminUserFactory, ClassGroupFactory, EnrollmentFactory, MinorClassGroupFactory,
    StudentFactory, SubjectOfferingFactory,
)


@pytest.fixture
def enrolled(academic_year):
    class_group = ClassGroupFactory(academic_year=academic_year)
    student = EnrollmentFactory(class_group=class_group).student
    maths = SubjectOfferingFactory(class_group=class_group)
    physics = SubjectOfferingFactory(class_group=class_group)
    return student, maths, physics


def detail(authenticated_client, student):
    return authenticated_client(AdminUserFactory()).get(
        reverse('home-api:student-detail', args=[student.user_id]),
    )


def test_grade_fields_come_from_teacher_entered_quarter_grades(
    enrolled, authenticated_client,
):
    student, maths, physics = enrolled
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=student, offering=physics, quarter=1, grade=4)
    QuarterGrade.objects.create(student=student, offering=maths, quarter=2, grade=3)

    response = detail(authenticated_client, student)

    assert response.status_code == 200
    assert response.data['total_quarter_grades'] == {'1': 4.5, '2': 3.0, '3': 0, '4': 0}
    assert response.data['cumulative_subject_grades'] == {
        maths.subject.name: 4.0, physics.subject.name: 4.0,
    }
    assert response.data['student_total_grade'] == 3.75


def test_ungraded_student_gets_zeroes(enrolled, authenticated_client):
    student, maths, physics = enrolled

    response = detail(authenticated_client, student)

    assert response.data['total_quarter_grades'] == {'1': 0, '2': 0, '3': 0, '4': 0}
    assert response.data['cumulative_subject_grades'] == {
        maths.subject.name: 0, physics.subject.name: 0,
    }
    assert response.data['student_total_grade'] == 0


def test_grades_outside_current_class_are_ignored(
    enrolled, authenticated_client, academic_year,
):
    student, _, _ = enrolled
    elsewhere = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    )
    QuarterGrade.objects.create(student=student, offering=elsewhere, quarter=1, grade=5)

    response = detail(authenticated_client, student)

    assert response.data['total_quarter_grades']['1'] == 0
    assert elsewhere.subject.name not in response.data['cumulative_subject_grades']


def test_minor_group_offerings_are_included(
    enrolled, authenticated_client, academic_year,
):
    student, maths, _ = enrolled
    subgroup = MinorClassGroupFactory(academic_year=academic_year)
    EnrollmentFactory(student=student, class_group=subgroup)
    english = SubjectOfferingFactory(class_group=subgroup)
    QuarterGrade.objects.create(student=student, offering=maths, quarter=1, grade=5)
    QuarterGrade.objects.create(student=student, offering=english, quarter=1, grade=3)

    response = detail(authenticated_client, student)

    assert english.id in [o['id'] for o in response.data['offerings']]
    assert response.data['subject_quarter_grades']['1'][english.subject.name] == 3
    assert response.data['total_quarter_grades']['1'] == 4.0
    assert response.data['cumulative_subject_grades'][english.subject.name] == 3.0


def test_minor_group_counts_without_a_major_class(authenticated_client, academic_year):
    student = StudentFactory()
    subgroup = MinorClassGroupFactory(academic_year=academic_year)
    EnrollmentFactory(student=student, class_group=subgroup)
    english = SubjectOfferingFactory(class_group=subgroup)
    QuarterGrade.objects.create(student=student, offering=english, quarter=2, grade=4)

    response = detail(authenticated_client, student)

    assert response.data['current_class_group'] is None
    assert response.data['total_quarter_grades']['2'] == 4.0
    assert response.data['student_total_grade'] == 4.0
