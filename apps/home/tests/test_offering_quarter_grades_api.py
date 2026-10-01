"""
Spec 0008 — quarter grades are managed per offering, in bulk.

    offerings/<offering_id>/quarter-grades/   GET / POST / PATCH / DELETE

Any staff member reads; only a teacher of the offering writes — not admin
roles, not the class's homeroom teacher. Each test is named after the AC it
pins down.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve, reverse

from apps.home.models import HomeroomTeacherAssignment, QuarterGrade
from core.factories import (
    AdminUserFactory, ClassGroupFactory, ClubManagerFactory, EnrollmentFactory,
    ParentFactory, SchoolFactory, StudentFactory, SubjectOfferingFactory,
    SupervisorFactory, TeacherFactory, TeachingAssignmentFactory, UserFactory,
)
from core.tenancy import school_scope


def url_for(offering):
    return reverse('home-api:offering-quarter-grades', args=[offering.id])


@pytest.fixture
def world(academic_year):
    """
    Maths for 7A, taught by `teacher`, with three enrolled students.

    `outsider` is a student in another class; `homeroom` is 7A's homeroom
    teacher, who does not teach maths; `other_teacher` teaches another offering.
    """
    class_group = ClassGroupFactory(academic_year=academic_year)
    offering = SubjectOfferingFactory(class_group=class_group)
    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=offering)

    students = [
        EnrollmentFactory(class_group=class_group).student for _ in range(3)
    ]
    outsider = EnrollmentFactory(
        class_group=ClassGroupFactory(academic_year=academic_year),
    ).student

    homeroom = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(teacher=homeroom, class_group=class_group)

    other_teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=other_teacher, offering=SubjectOfferingFactory())

    return {
        'offering': offering, 'teacher': teacher, 'students': students,
        'outsider': outsider, 'homeroom': homeroom, 'other_teacher': other_teacher,
    }


def grade(world, student, quarter=1, value=4):
    return QuarterGrade.objects.create(
        offering=world['offering'], student=student, quarter=quarter, grade=value,
    )


def grades_payload(quarter, pairs):
    return {'quarter': quarter, 'grades': {str(s.id): g for s, g in pairs}}


def stored(world):
    return {
        (row.student_id, row.quarter): row.grade
        for row in QuarterGrade.objects.filter(offering=world['offering'])
    }


# ── Reads ──

@pytest.mark.parametrize('make_user', [
    lambda: AdminUserFactory(),
    lambda: SupervisorFactory().user,
    lambda: UserFactory(group_name='Principal'),
    lambda: UserFactory(group_name='Psychologist'),
    lambda: TeacherFactory().user,
    lambda: UserFactory(group_name='HomeroomTeacher'),
])
def test_ac1_staff_read_any_offering(world, authenticated_client, make_user):
    s1, s2, _ = world['students']
    grade(world, s1, quarter=1, value=5)
    grade(world, s2, quarter=2, value=3)

    response = authenticated_client(make_user()).get(url_for(world['offering']))

    assert response.status_code == 200
    assert {(r['student'], r['quarter'], r['grade']) for r in response.data} == {
        (s1.id, 1, 5), (s2.id, 2, 3),
    }


def test_ac2_quarter_filter(world, authenticated_client):
    s1, s2, _ = world['students']
    grade(world, s1, quarter=1)
    grade(world, s2, quarter=2)

    client = authenticated_client(world['teacher'].user)
    response = client.get(url_for(world['offering']), {'quarter': 2})

    assert [r['student'] for r in response.data] == [s2.id]


# ── Non-staff ──

@pytest.mark.parametrize('make_user', [
    lambda world: world['students'][0].user,
    lambda world: ParentFactory().user,
    lambda world: ClubManagerFactory().user,
])
@pytest.mark.parametrize('method', ['get', 'post', 'patch', 'delete'])
def test_ac3_students_parents_and_club_managers_are_403(
    world, authenticated_client, make_user, method,
):
    grade(world, world['students'][0])
    client = authenticated_client(make_user(world))

    response = getattr(client, method)(url_for(world['offering']), {}, format='json')

    assert response.status_code == 403


@pytest.mark.parametrize('method', ['get', 'post', 'patch', 'delete'])
def test_ac3_anonymous_is_401(world, api_client, method):
    response = getattr(api_client, method)(url_for(world['offering']), {}, format='json')
    assert response.status_code == 401


# ── Create ──

def test_ac4_teacher_creates_a_quarter_in_one_request(world, authenticated_client):
    s1, s2, s3 = world['students']
    client = authenticated_client(world['teacher'].user)

    response = client.post(
        url_for(world['offering']),
        grades_payload(3, [(s1, 5), (s2, 4), (s3, 2)]), format='json',
    )

    assert response.status_code == 201
    assert {(r['student'], r['grade']) for r in response.data} == {
        (s1.id, 5), (s2.id, 4), (s3.id, 2),
    }
    assert stored(world) == {(s1.id, 3): 5, (s2.id, 3): 4, (s3.id, 3): 2}


# ── Who may write ──

@pytest.mark.parametrize('who', ['admin', 'supervisor', 'other_teacher', 'homeroom'])
@pytest.mark.parametrize('method', ['post', 'patch', 'delete'])
def test_ac5_only_teachers_of_the_offering_write(
    world, authenticated_client, who, method,
):
    s1 = world['students'][0]
    grade(world, s1, quarter=1, value=4)
    user = {
        'admin': lambda: AdminUserFactory(),
        'supervisor': lambda: SupervisorFactory().user,
        'other_teacher': lambda: world['other_teacher'].user,
        'homeroom': lambda: world['homeroom'].user,
    }[who]()
    payload = (
        {'quarter': 1, 'students': [s1.id]} if method == 'delete'
        else grades_payload(1, [(s1, 2)])
    )

    response = getattr(authenticated_client(user), method)(
        url_for(world['offering']), payload, format='json',
    )

    assert response.status_code == 403
    assert stored(world) == {(s1.id, 1): 4}


def test_ac5_co_teacher_of_the_offering_may_write(world, authenticated_client):
    co_teacher = TeacherFactory()
    TeachingAssignmentFactory(
        teacher=co_teacher, offering=world['offering'], role='assistant',
    )
    s1 = world['students'][0]

    response = authenticated_client(co_teacher.user).post(
        url_for(world['offering']), grades_payload(1, [(s1, 5)]), format='json',
    )

    assert response.status_code == 201


def test_ac6_post_refuses_already_graded_students_and_writes_nothing(
    world, authenticated_client,
):
    s1, s2, _ = world['students']
    grade(world, s1, quarter=1, value=4)
    client = authenticated_client(world['teacher'].user)

    response = client.post(
        url_for(world['offering']),
        grades_payload(1, [(s1, 5), (s2, 5)]), format='json',
    )

    assert response.status_code == 400
    assert set(response.data['grades']) == {str(s1.id)}
    assert stored(world) == {(s1.id, 1): 4}


@pytest.mark.parametrize('method', ['post', 'patch'])
def test_ac7_unenrolled_student_fails_the_whole_request(
    world, authenticated_client, method,
):
    s1 = world['students'][0]
    if method == 'patch':
        grade(world, s1, quarter=1, value=4)
    client = authenticated_client(world['teacher'].user)

    response = getattr(client, method)(
        url_for(world['offering']),
        grades_payload(1, [(s1, 5), (world['outsider'], 5)]), format='json',
    )

    assert response.status_code == 400
    assert str(world['outsider'].id) in response.data['grades']
    expected = {(s1.id, 1): 4} if method == 'patch' else {}
    assert stored(world) == expected


@pytest.mark.parametrize('bad_grade', [1, 6])
@pytest.mark.parametrize('method', ['post', 'patch'])
def test_ac7_grade_outside_2_to_5_fails_the_whole_request(
    world, authenticated_client, method, bad_grade,
):
    s1, s2, _ = world['students']
    if method == 'patch':
        grade(world, s1, quarter=1, value=4)
        grade(world, s2, quarter=1, value=4)
    client = authenticated_client(world['teacher'].user)

    response = getattr(client, method)(
        url_for(world['offering']),
        grades_payload(1, [(s1, 5), (s2, bad_grade)]), format='json',
    )

    assert response.status_code == 400
    assert set(response.data['grades']) == {str(s2.id)}
    expected = {(s1.id, 1): 4, (s2.id, 1): 4} if method == 'patch' else {}
    assert stored(world) == expected


# ── Update ──

def test_ac8_patch_updates_listed_students_only(world, authenticated_client):
    s1, s2, s3 = world['students']
    grade(world, s1, quarter=2, value=3)
    grade(world, s2, quarter=2, value=3)
    grade(world, s3, quarter=2, value=3)
    client = authenticated_client(world['teacher'].user)

    response = client.patch(
        url_for(world['offering']),
        grades_payload(2, [(s1, 5), (s2, 4)]), format='json',
    )

    assert response.status_code == 200
    assert {(r['student'], r['grade']) for r in response.data} == {(s1.id, 5), (s2.id, 4)}
    assert stored(world) == {(s1.id, 2): 5, (s2.id, 2): 4, (s3.id, 2): 3}


def test_ac8_patch_refuses_ungraded_students_and_writes_nothing(
    world, authenticated_client,
):
    s1, s2, _ = world['students']
    grade(world, s1, quarter=2, value=3)
    client = authenticated_client(world['teacher'].user)

    response = client.patch(
        url_for(world['offering']),
        grades_payload(2, [(s1, 5), (s2, 5)]), format='json',
    )

    assert response.status_code == 400
    assert set(response.data['grades']) == {str(s2.id)}
    assert stored(world) == {(s1.id, 2): 3}


# ── Delete ──

def test_ac9_delete_removes_listed_students(world, authenticated_client):
    s1, s2, s3 = world['students']
    grade(world, s1, quarter=1)
    grade(world, s2, quarter=1)
    grade(world, s1, quarter=2)
    client = authenticated_client(world['teacher'].user)

    response = client.delete(
        url_for(world['offering']),
        {'quarter': 1, 'students': [s1.id, s2.id]}, format='json',
    )

    assert response.status_code == 204
    assert stored(world) == {(s1.id, 2): 4}


def test_ac9_delete_refuses_ungraded_students_and_deletes_nothing(
    world, authenticated_client,
):
    s1, s2, _ = world['students']
    grade(world, s1, quarter=1)
    client = authenticated_client(world['teacher'].user)

    response = client.delete(
        url_for(world['offering']),
        {'quarter': 1, 'students': [s1.id, s2.id]}, format='json',
    )

    assert response.status_code == 400
    assert stored(world) == {(s1.id, 1): 4}


# ── Offering lookup ──

def test_ac10_missing_offering_is_404(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)
    url = reverse('home-api:offering-quarter-grades', args=[999999])

    assert client.get(url).status_code == 404
    assert client.post(url, grades_payload(1, []), format='json').status_code == 404


def test_ac10_other_schools_offering_is_404(world, authenticated_client, settings):
    settings.SCHOOL_SCOPE_MODE = 'enforce'
    with school_scope(SchoolFactory(slug='school_b')):
        foreign = SubjectOfferingFactory()

    client = authenticated_client(AdminUserFactory())

    assert client.get(url_for(foreign)).status_code == 404


# ── Old routes and the admin ──

@pytest.mark.parametrize('path', ['/api/v1/quarter-grades/', '/api/v1/quarter-grades/1/'])
def test_ac11_flat_quarter_grade_routes_are_gone(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_ac12_quarter_grade_is_not_in_django_admin():
    assert not admin.site.is_registered(QuarterGrade)
