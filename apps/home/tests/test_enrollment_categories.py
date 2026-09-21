"""
Tests for the major/minor split on ClassGroup.

A student belongs to exactly one major class group per academic year — that is
their class — but may join any number of minor groups alongside it. Enrolling
into a major group replaces the previous one; enrolling into a minor group adds
to what they already have and never disturbs the major.
"""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.home.models import ClassGroup, Enrollment
from core.factories import (
    AcademicYearFactory, ClassGroupFactory, EnrollmentFactory, StudentFactory,
)


@pytest.fixture
def year(academic_year):
    return academic_year


@pytest.fixture
def major_a(year):
    return ClassGroupFactory(academic_year=year, letter='A')


@pytest.fixture
def major_b(year):
    return ClassGroupFactory(academic_year=year, letter='B')


@pytest.fixture
def minor_chess(year):
    return ClassGroupFactory(
        academic_year=year, letter='Chess', category=ClassGroup.MINOR_CHOICE,
    )


@pytest.fixture
def minor_robotics(year):
    return ClassGroupFactory(
        academic_year=year, letter='Robotics', category=ClassGroup.MINOR_CHOICE,
    )


def active_groups(student):
    return set(
        Enrollment.objects.filter(student=student, status='active')
        .values_list('class_group_id', flat=True)
    )


def test_enrolling_in_second_major_replaces_the_first(student, major_a, major_b, year):
    Enrollment.enroll_student(student, major_a, year)
    Enrollment.enroll_student(student, major_b, year)

    assert active_groups(student) == {major_b.id}
    first = Enrollment.objects.get(student=student, class_group=major_a)
    assert first.status == 'transferred'
    assert first.end_date is not None


def test_student_can_hold_many_minor_groups(student, major_a, minor_chess, minor_robotics, year):
    Enrollment.enroll_student(student, major_a, year)
    Enrollment.enroll_student(student, minor_chess, year)
    Enrollment.enroll_student(student, minor_robotics, year)

    assert active_groups(student) == {major_a.id, minor_chess.id, minor_robotics.id}


def test_minor_enrollment_leaves_the_major_untouched(student, major_a, minor_chess, year):
    Enrollment.enroll_student(student, major_a, year)
    Enrollment.enroll_student(student, minor_chess, year)

    assert student.get_current_class_group() == major_a
    assert student.get_current_minor_class_groups() == [minor_chess]


def test_switching_major_keeps_minor_groups(student, major_a, major_b, minor_chess, year):
    Enrollment.enroll_student(student, major_a, year)
    Enrollment.enroll_student(student, minor_chess, year)
    Enrollment.enroll_student(student, major_b, year)

    assert active_groups(student) == {major_b.id, minor_chess.id}


def test_re_enrolling_in_the_same_group_reuses_the_enrollment(student, minor_chess, year):
    first = Enrollment.enroll_student(student, minor_chess, year)
    second = Enrollment.enroll_student(student, minor_chess, year)

    assert first.pk == second.pk
    assert Enrollment.objects.filter(student=student, class_group=minor_chess).count() == 1


def test_second_active_major_is_rejected_on_save(student, major_a, major_b):
    EnrollmentFactory(student=student, class_group=major_a)

    with pytest.raises(ValidationError) as exc:
        EnrollmentFactory(student=student, class_group=major_b)

    assert 'class_group' in exc.value.message_dict


def test_second_active_major_is_rejected_by_full_clean(student, major_a, major_b):
    EnrollmentFactory(student=student, class_group=major_a)

    conflicting = Enrollment(student=student, class_group=major_b, status='active')
    with pytest.raises(ValidationError):
        conflicting.full_clean(exclude=['start_date', 'end_date'])


def test_inactive_major_does_not_block_a_new_one(student, major_a, major_b):
    EnrollmentFactory(student=student, class_group=major_a, status='transferred')

    EnrollmentFactory(student=student, class_group=major_b)

    assert active_groups(student) == {major_b.id}


def test_major_in_another_year_does_not_conflict(student, major_a):
    next_year = AcademicYearFactory(is_active=False, year='2030-2031')
    next_year_class = ClassGroupFactory(academic_year=next_year, letter='A')

    EnrollmentFactory(student=student, class_group=major_a)
    EnrollmentFactory(student=student, class_group=next_year_class)

    assert active_groups(student) == {major_a.id, next_year_class.id}


def test_two_minor_groups_never_conflict(student, minor_chess, minor_robotics):
    EnrollmentFactory(student=student, class_group=minor_chess)
    EnrollmentFactory(student=student, class_group=minor_robotics)

    assert active_groups(student) == {minor_chess.id, minor_robotics.id}


def test_current_enrollment_ignores_minor_groups(student, minor_chess):
    EnrollmentFactory(student=student, class_group=minor_chess)

    assert student.get_current_enrollment() is None
    assert student.get_current_class_group() is None


def test_class_group_list_can_be_filtered_by_category(
    authenticated_client, admin_user, major_a, minor_chess
):
    client = authenticated_client(admin_user)
    url = reverse('home-api:class-groups')

    majors = client.get(url, {'category': ClassGroup.MAJOR_CHOICE})
    minors = client.get(url, {'category': ClassGroup.MINOR_CHOICE})

    assert {group['id'] for group in majors.data} == {major_a.id}
    assert {group['id'] for group in minors.data} == {minor_chess.id}
    assert minors.data[0]['category'] == ClassGroup.MINOR_CHOICE


def test_other_students_are_unaffected(major_a, minor_chess, year):
    one = StudentFactory()
    other = StudentFactory()

    Enrollment.enroll_student(one, major_a, year)
    Enrollment.enroll_student(other, major_a, year)
    Enrollment.enroll_student(other, minor_chess, year)

    assert active_groups(one) == {major_a.id}
    assert active_groups(other) == {major_a.id, minor_chess.id}
