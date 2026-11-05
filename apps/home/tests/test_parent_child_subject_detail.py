"""
A parent's view of one child's subject: a subject the child's class does not
take returns empty grades rather than a 500, and a parent can only open their
own children. A subject taught in one of the child's minor groups (подгруппы)
is found there, and the teacher shown is the one assigned to that offering.
"""

import pytest
from django.urls import reverse

from core.factories import (
    ClassGroupFactory, EnrollmentFactory, LessonFactory, MinorClassGroupFactory,
    ParentFactory, StudentFactory, SubjectFactory, SubjectOfferingFactory,
    TeacherFactory, TeachingAssignmentFactory,
)


@pytest.fixture
def enrolled(academic_year):
    class_group = ClassGroupFactory(academic_year=academic_year)
    student = EnrollmentFactory(class_group=class_group).student
    parent = ParentFactory()
    parent.students.add(student)
    return parent, student, class_group


def url(student, subject):
    return reverse('home-api:parent-child-subject-detail', args=[student.pk, subject.pk])


def test_subject_not_offered_to_childs_class_returns_empty_grades(enrolled, authenticated_client):
    parent, student, _ = enrolled
    subject = SubjectFactory()

    response = authenticated_client(parent.user).get(url(student, subject))

    assert response.status_code == 200
    assert response.data['lessons'] == []
    assert response.data['cumulative_grade'] == 0


def test_offered_subject_without_lessons_returns_empty_grades(enrolled, authenticated_client):
    parent, student, class_group = enrolled
    offering = SubjectOfferingFactory(class_group=class_group)

    response = authenticated_client(parent.user).get(url(student, offering.subject))

    assert response.status_code == 200
    assert response.data['lessons'] == []


def test_parent_cannot_open_another_parents_child(enrolled, authenticated_client):
    _, student, class_group = enrolled
    offering = SubjectOfferingFactory(class_group=class_group)
    stranger = ParentFactory()

    response = authenticated_client(stranger.user).get(url(student, offering.subject))

    assert response.status_code == 404


def test_subject_taught_in_minor_group_returns_its_lessons(enrolled, authenticated_client, academic_year):
    parent, student, _ = enrolled
    minor = MinorClassGroupFactory(academic_year=academic_year)
    EnrollmentFactory(student=student, class_group=minor)
    offering = SubjectOfferingFactory(class_group=minor)
    lesson = LessonFactory(offering=offering)

    response = authenticated_client(parent.user).get(url(student, offering.subject))

    assert response.status_code == 200
    assert [ls['lesson_id'] for ls in response.data['lessons']] == [lesson.pk]
    assert response.data['class_group_name'] == str(minor)


def test_child_with_only_minor_enrollment_is_served(authenticated_client, academic_year):
    minor = MinorClassGroupFactory(academic_year=academic_year)
    student = EnrollmentFactory(class_group=minor).student
    parent = ParentFactory()
    parent.students.add(student)
    offering = SubjectOfferingFactory(class_group=minor)
    LessonFactory(offering=offering)

    response = authenticated_client(parent.user).get(url(student, offering.subject))

    assert response.status_code == 200
    assert len(response.data['lessons']) == 1


def test_child_without_any_enrollment_is_rejected(authenticated_client, academic_year):
    student = StudentFactory()
    parent = ParentFactory()
    parent.students.add(student)

    response = authenticated_client(parent.user).get(url(student, SubjectFactory()))

    assert response.status_code == 400


def test_teacher_is_the_one_assigned_to_childs_offering(enrolled, authenticated_client, academic_year):
    parent, student, class_group = enrolled
    offering = SubjectOfferingFactory(class_group=class_group)
    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')
    other_offering = SubjectOfferingFactory(class_group=other_class, subject=offering.subject)
    TeachingAssignmentFactory(offering=other_offering)
    TeachingAssignmentFactory(offering=offering, role='assistant')
    primary = TeachingAssignmentFactory(offering=offering, role='primary').teacher
    TeacherFactory().subjects.add(offering.subject)

    response = authenticated_client(parent.user).get(url(student, offering.subject))

    assert response.status_code == 200
    assert response.data['teacher']['id'] == primary.pk
