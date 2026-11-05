"""Acceptance tests for spec 0015 temporal teaching assignments."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.home.models import SubjectGrade, TeachingAssignment
from apps.home.teaching_assignments import replace_assignment
from core.factories import (
    AcademicYearFactory, ClassGroupFactory, EnrollmentFactory,
    SubjectAssignmentFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory, UserFactory,
)


D = date


@pytest.fixture
def temporal_world(db):
    year = AcademicYearFactory(
        year='2026/2027', archived=False, is_active=True,
        q1_start=D(2026, 9, 1), q1_end=D(2026, 11, 30),
        q2_start=D(2026, 12, 1), q2_end=D(2027, 2, 28),
        q3_start=D(2027, 3, 1), q3_end=D(2027, 4, 30),
        q4_start=D(2027, 5, 1), q4_end=D(2027, 6, 30),
    )
    class_group = ClassGroupFactory(academic_year=year)
    offering = SubjectOfferingFactory(class_group=class_group)
    old_teacher = TeacherFactory()
    old_ta = TeachingAssignmentFactory(
        offering=offering, teacher=old_teacher, start_date=D(2026, 9, 1),
    )
    student = EnrollmentFactory(class_group=class_group).student
    return {
        'year': year,
        'offering': offering,
        'old_teacher': old_teacher,
        'old_ta': old_ta,
        'student': student,
    }


@pytest.mark.django_db
def test_ac1_replacement_closes_old_row_and_creates_open_row(temporal_world):
    new_teacher = TeacherFactory()

    replacement = replace_assignment(
        assignment=temporal_world['old_ta'],
        new_teacher=new_teacher,
        effective_date=D(2026, 10, 1),
    )

    old = TeachingAssignment.objects.get(pk=temporal_world['old_ta'].pk)
    assert old.teacher == temporal_world['old_teacher']
    assert old.end_date == D(2026, 9, 30)
    assert replacement.pk != old.pk
    assert replacement.teacher == new_teacher
    assert replacement.start_date == D(2026, 10, 1)
    assert replacement.end_date is None
    assert replacement.is_current


@pytest.mark.parametrize(
    'final_start_date',
    [D(2026, 10, 1), D(2026, 10, 2)],
)
@pytest.mark.django_db
def test_ac14_zero_or_one_day_replacement_hard_deletes_superseded_row(
    temporal_world, final_start_date,
):
    first_replacement = replace_assignment(
        assignment=temporal_world['old_ta'],
        new_teacher=TeacherFactory(),
        effective_date=D(2026, 10, 1),
    )
    final_teacher = TeacherFactory()

    final_replacement = replace_assignment(
        assignment=first_replacement,
        new_teacher=final_teacher,
        effective_date=final_start_date,
    )

    assert not TeachingAssignment._base_manager.filter(
        pk=first_replacement.pk,
    ).exists()
    assert final_replacement.teacher == final_teacher
    assert final_replacement.start_date == final_start_date
    assert final_replacement.end_date is None
    old = TeachingAssignment.objects.get(pk=temporal_world['old_ta'].pk)
    assert old.end_date == D(2026, 9, 30)


@pytest.mark.django_db
def test_ac14_admin_accepts_a_second_replacement_on_the_same_day(
    temporal_world, client,
):
    first_replacement = replace_assignment(
        assignment=temporal_world['old_ta'],
        new_teacher=TeacherFactory(),
        effective_date=D(2026, 10, 1),
    )
    final_teacher = TeacherFactory()
    admin_user = UserFactory(
        school=temporal_world['offering'].school,
        is_staff=True,
        is_superuser=True,
    )
    client.post(
        reverse('admin:login'),
        {
            'username': admin_user.username,
            'password': 'testpass123',
            'next': '/admin/',
        },
    )

    response = client.post(
        reverse(
            'admin:home_teachingassignment_change',
            args=[first_replacement.pk],
        ),
        {
            'replacement_teacher': final_teacher.pk,
            'replacement_date': '2026-10-01',
            '_save': 'Save',
        },
    )

    assert response.status_code == 302
    assert not TeachingAssignment._base_manager.filter(
        pk=first_replacement.pk,
    ).exists()
    assert TeachingAssignment.objects.filter(
        offering=temporal_world['offering'],
        teacher=final_teacher,
        start_date=D(2026, 10, 1),
        end_date__isnull=True,
    ).exists()


@pytest.mark.django_db
def test_ac2_historical_identity_is_immutable(temporal_world):
    assignment = temporal_world['old_ta']
    assignment.teacher = TeacherFactory()

    with pytest.raises(ValidationError, match='historical identity'):
        assignment.save()


@pytest.mark.django_db
def test_ac3_different_teachers_overlap_but_same_teacher_cannot(
    temporal_world,
):
    TeachingAssignmentFactory(
        offering=temporal_world['offering'],
        teacher=TeacherFactory(),
        start_date=D(2026, 9, 15),
    )

    with pytest.raises(ValidationError, match='overlapping assignment'):
        TeachingAssignmentFactory(
            offering=temporal_world['offering'],
            teacher=temporal_world['old_teacher'],
            start_date=D(2026, 9, 15),
        )


@pytest.mark.django_db
def test_ac4_to_ac7_grade_writes_follow_teacher_periods(
    temporal_world, authenticated_client,
):
    new_teacher = TeacherFactory()
    replace_assignment(
        assignment=temporal_world['old_ta'],
        new_teacher=new_teacher,
        effective_date=D(2026, 10, 1),
    )
    q1_work = SubjectAssignmentFactory(
        offering=temporal_world['offering'], date=D(2026, 9, 20),
    )
    q2_work = SubjectAssignmentFactory(
        offering=temporal_world['offering'], date=D(2026, 10, 20),
    )
    q1_url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[q1_work.pk],
    )
    q2_url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[q2_work.pk],
    )
    payload = {'student': temporal_world['student'].pk, 'grade': 8}

    old_client = authenticated_client(temporal_world['old_teacher'].user)
    assert old_client.post(q1_url, payload, format='json').status_code == 201
    assert old_client.post(q2_url, payload, format='json').status_code == 403

    SubjectGrade.objects.filter(assignment=q1_work).delete()
    new_client = authenticated_client(new_teacher.user)
    assert new_client.post(q1_url, payload, format='json').status_code == 403
    assert new_client.post(q2_url, payload, format='json').status_code == 201


@pytest.mark.django_db
def test_ac8_quarter_grade_uses_quarter_end_teacher(
    temporal_world, authenticated_client,
):
    new_teacher = TeacherFactory()
    replace_assignment(
        assignment=temporal_world['old_ta'],
        new_teacher=new_teacher,
        effective_date=D(2026, 10, 1),
    )
    url = reverse(
        'home-api:offering-quarter-grades',
        args=[temporal_world['offering'].pk],
    )
    payload = {
        'quarter': 1,
        'grades': {str(temporal_world['student'].pk): 5},
    }

    old_client = authenticated_client(temporal_world['old_teacher'].user)
    old_response = old_client.post(url, payload, format='json')
    new_response = authenticated_client(new_teacher.user).post(
        url, payload, format='json',
    )

    assert old_response.status_code == 403
    assert new_response.status_code == 201


@pytest.mark.django_db
def test_ac11_archived_year_locks_teacher_writes(
    temporal_world, authenticated_client,
):
    assignment = SubjectAssignmentFactory(
        offering=temporal_world['offering'], date=D(2026, 9, 20),
    )
    temporal_world['year'].archived = True
    temporal_world['year'].save(update_fields=['archived'])
    url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[assignment.pk],
    )

    response = authenticated_client(temporal_world['old_teacher'].user).post(
        url,
        {'student': temporal_world['student'].pk, 'grade': 8},
        format='json',
    )

    assert response.status_code == 403
