"""
Tests that `get_students_for_role` lists every student exactly once.

A student sits in one major class group but any number of подгруппы, so each of
their active enrollments used to produce a separate entry in the list. The
student belongs in the list once, under their major class group.
"""

import pytest

from apps.home.models import ClassGroup, Enrollment
from apps.home.services import get_students_for_role
from core.factories import ClassGroupFactory, StudentFactory


@pytest.fixture
def major_a(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='A')


@pytest.fixture
def minor_chess(academic_year):
    return ClassGroupFactory(
        academic_year=academic_year, letter='Chess',
        category=ClassGroup.MINOR_CHOICE,
    )


@pytest.fixture
def minor_robotics(academic_year):
    return ClassGroupFactory(
        academic_year=academic_year, letter='Robotics',
        category=ClassGroup.MINOR_CHOICE,
    )


def test_student_in_several_groups_is_listed_once(
    admin_user, student, academic_year, major_a, minor_chess, minor_robotics,
):
    Enrollment.enroll_student(student, major_a, academic_year)
    Enrollment.enroll_student(student, minor_chess, academic_year)
    Enrollment.enroll_student(student, minor_robotics, academic_year)

    students = get_students_for_role(admin_user, year_id=academic_year.id)

    assert [s.id for s in students] == [student.id]
    assert students[0].classroom == major_a


def test_classroom_is_the_major_group_even_with_no_major_first(
    admin_user, student, academic_year, major_a, minor_chess,
):
    # Minor enrollment created first, so ordering cannot rely on insertion order
    Enrollment.enroll_student(student, minor_chess, academic_year)
    Enrollment.enroll_student(student, major_a, academic_year)

    students = get_students_for_role(admin_user, year_id=academic_year.id)

    assert len(students) == 1
    assert students[0].classroom == major_a


def test_student_with_only_minor_enrollments_is_still_listed(
    admin_user, student, academic_year, minor_chess,
):
    Enrollment.enroll_student(student, minor_chess, academic_year)

    students = get_students_for_role(admin_user, year_id=academic_year.id)

    assert [s.id for s in students] == [student.id]
    assert students[0].classroom == minor_chess


def test_filtering_by_minor_group_returns_its_members_once(
    admin_user, student, academic_year, major_a, minor_chess,
):
    other = StudentFactory()
    Enrollment.enroll_student(student, major_a, academic_year)
    Enrollment.enroll_student(student, minor_chess, academic_year)
    Enrollment.enroll_student(other, major_a, academic_year)

    students = get_students_for_role(
        admin_user, year_id=academic_year.id, class_group_id=minor_chess.id,
    )

    assert [s.id for s in students] == [student.id]


def test_every_enrolled_student_appears_exactly_once(
    admin_user, student, academic_year, major_a, minor_chess, minor_robotics,
):
    second = StudentFactory()
    third = StudentFactory()
    for s in (student, second, third):
        Enrollment.enroll_student(s, major_a, academic_year)
    Enrollment.enroll_student(second, minor_chess, academic_year)
    Enrollment.enroll_student(third, minor_chess, academic_year)
    Enrollment.enroll_student(third, minor_robotics, academic_year)

    students = get_students_for_role(admin_user, year_id=academic_year.id)

    ids = [s.id for s in students]
    assert sorted(ids) == sorted([student.id, second.id, third.id])
    assert len(ids) == len(set(ids))
