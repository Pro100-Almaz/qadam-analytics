"""
Spec 0012 — role-scoped offering endpoints.

teacher/offerings/ answers for the teaching role only, homeroom/my-class/ for
the homeroom role only, and the mixed analytics/assignment-offerings/ is gone.
Each test is named after the AC it pins down.
"""

import pytest
from django.contrib.auth.models import Group
from django.urls import Resolver404, resolve, reverse

from apps.home.models import HomeroomTeacherAssignment
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory, EnrollmentFactory,
    SubjectAssignmentFactory, SubjectFactory, SubjectOfferingFactory,
    TeacherFactory, TeachingAssignmentFactory,
)


def offerings_url():
    return reverse('home-api:teacher-offering-list')


def my_class_url():
    return reverse('home-api:homeroom-my-class')


def make_homeroom_teacher(teacher, class_group):
    group, _ = Group.objects.get_or_create(name='HomeroomTeacher')
    teacher.user.groups.add(group)
    HomeroomTeacherAssignment.objects.create(
        teacher=teacher, class_group=class_group,
    )


@pytest.fixture
def setup(db):
    """
    One teacher teaching Mathematics in their own homeroom class, where
    Chinese is taught by someone else, plus an unrelated offering elsewhere.
    """
    academic_year = AcademicYearFactory(is_active=True)
    class_group = ClassGroupFactory(academic_year=academic_year, letter='A')
    teacher = TeacherFactory()
    taught = SubjectOfferingFactory(
        subject=SubjectFactory(name='Mathematics'), class_group=class_group,
    )
    TeachingAssignmentFactory(teacher=teacher, offering=taught, role='primary')

    other_teacher = TeacherFactory()
    not_taught = SubjectOfferingFactory(
        subject=SubjectFactory(name='Chinese'), class_group=class_group,
    )
    TeachingAssignmentFactory(teacher=other_teacher, offering=not_taught)

    unrelated = SubjectOfferingFactory(
        subject=SubjectFactory(name='Physics'),
        class_group=ClassGroupFactory(academic_year=academic_year, letter='Z'),
    )
    return {
        'academic_year': academic_year,
        'class_group': class_group,
        'teacher': teacher,
        'other_teacher': other_teacher,
        'taught': taught,
        'not_taught': not_taught,
        'unrelated': unrelated,
    }


# ── teacher/offerings/ ──

def test_ac1_teacher_offerings_lists_only_taught_offerings(
    setup, authenticated_client,
):
    archived = SubjectOfferingFactory(
        subject=SubjectFactory(name='Latin', status='archived'),
        class_group=setup['class_group'],
    )
    TeachingAssignmentFactory(teacher=setup['teacher'], offering=archived)

    response = authenticated_client(setup['teacher'].user).get(offerings_url())

    assert response.status_code == 200, response.data
    assert [row['id'] for row in response.data['offerings']] == [
        setup['taught'].id,
    ]
    assert response.data['count'] == 1
    assert response.data['teacher']['id'] == setup['teacher'].id
    assert response.data['academic_year']['id'] == setup['academic_year'].id


def test_ac1_teacher_offerings_respects_academic_year(
    setup, authenticated_client,
):
    other_year = AcademicYearFactory(is_active=False)
    old = SubjectOfferingFactory(
        class_group=ClassGroupFactory(academic_year=other_year),
    )
    TeachingAssignmentFactory(teacher=setup['teacher'], offering=old)

    response = authenticated_client(setup['teacher'].user).get(
        offerings_url(), {'academic_year': other_year.id},
    )

    assert response.status_code == 200
    assert [row['id'] for row in response.data['offerings']] == [old.id]


def test_ac2_homeroom_teacher_gets_no_untaught_homeroom_offerings(
    setup, authenticated_client,
):
    make_homeroom_teacher(setup['teacher'], setup['class_group'])

    response = authenticated_client(setup['teacher'].user).get(offerings_url())

    assert response.status_code == 200
    ids = {row['id'] for row in response.data['offerings']}
    assert ids == {setup['taught'].id}
    assert setup['not_taught'].id not in ids


def test_ac3_include_empty_false_drops_offerings_without_assignments(
    setup, authenticated_client,
):
    empty = SubjectOfferingFactory(
        subject=SubjectFactory(name='Biology'), class_group=setup['class_group'],
    )
    TeachingAssignmentFactory(teacher=setup['teacher'], offering=empty)
    SubjectAssignmentFactory(offering=setup['taught'])
    SubjectAssignmentFactory(offering=setup['taught'])
    client = authenticated_client(setup['teacher'].user)

    default = client.get(offerings_url())
    filtered = client.get(offerings_url(), {'include_empty': 'false'})

    assert {row['id'] for row in default.data['offerings']} == {
        setup['taught'].id, empty.id,
    }
    assert [row['id'] for row in filtered.data['offerings']] == [
        setup['taught'].id,
    ]


def test_ac4_rows_carry_teaching_role_and_no_homeroom_fields(
    setup, authenticated_client,
):
    make_homeroom_teacher(setup['teacher'], setup['class_group'])

    response = authenticated_client(setup['teacher'].user).get(offerings_url())

    [row] = response.data['offerings']
    assert row['teaching_role'] == 'primary'
    assert row['class_group_id'] == setup['class_group'].id
    assert 'access' not in row
    assert 'is_homeroom_class' not in row


def test_ac5_teacher_offerings_is_403_outside_the_teacher_roles(
    db, authenticated_client,
):
    response = authenticated_client(AdminUserFactory()).get(offerings_url())

    assert response.status_code == 403


# ── homeroom/my-class/ ──

def test_ac6_homeroom_my_class_returns_class_students_and_offerings(
    setup, authenticated_client,
):
    make_homeroom_teacher(setup['teacher'], setup['class_group'])
    enrollment = EnrollmentFactory(class_group=setup['class_group'])

    response = authenticated_client(setup['teacher'].user).get(my_class_url())

    assert response.status_code == 200, response.data
    assert response.data['class_group_id'] == setup['class_group'].id
    assert [s['student_id'] for s in response.data['students']] == [
        enrollment.student_id,
    ]
    offerings = {o['id']: o for o in response.data['offerings']}
    assert set(offerings) == {setup['taught'].id, setup['not_taught'].id}
    assert [t['id'] for t in offerings[setup['not_taught'].id]['teachers']] == [
        setup['other_teacher'].id,
    ]
    assert {
        s['offering_id'] for s in response.data['students'][0]['subjects']
    } == set(offerings)


def test_ac7_homeroom_my_class_is_403_outside_the_homeroom_role(
    setup, authenticated_client,
):
    teacher_response = authenticated_client(setup['teacher'].user).get(
        my_class_url(),
    )
    admin_response = authenticated_client(AdminUserFactory()).get(
        my_class_url(),
    )

    assert teacher_response.status_code == 403
    assert admin_response.status_code == 403


def test_ac7_homeroom_my_class_is_404_without_a_class(
    setup, authenticated_client,
):
    group, _ = Group.objects.get_or_create(name='HomeroomTeacher')
    setup['teacher'].user.groups.add(group)

    response = authenticated_client(setup['teacher'].user).get(my_class_url())

    assert response.status_code == 404


# ── Removed routes ──

@pytest.mark.parametrize('path', [
    '/api/v1/teacher/my-class/',
    '/api/v1/analytics/assignment-offerings/',
])
def test_ac8_old_routes_are_gone(path):
    with pytest.raises(Resolver404):
        resolve(path)
