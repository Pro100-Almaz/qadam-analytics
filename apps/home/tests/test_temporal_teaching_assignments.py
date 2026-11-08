"""Acceptance tests for quarter-based teaching assignment authority."""

from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.home.models import SubjectGrade
from core.factories import (
    AcademicYearFactory, ClassGroupFactory, EnrollmentFactory,
    SubjectAssignmentFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory,
)


@pytest.fixture
def quarter_world(db):
    year = AcademicYearFactory(
        year='2026/2027', archived=False, is_active=True,
        q1_start=date(2026, 9, 1), q1_end=date(2026, 11, 30),
        q2_start=date(2026, 12, 1), q2_end=date(2027, 2, 28),
    )
    class_group = ClassGroupFactory(academic_year=year)
    offering = SubjectOfferingFactory(class_group=class_group)
    q1_teacher = TeacherFactory()
    q2_teacher = TeacherFactory()
    q1_ta = TeachingAssignmentFactory(
        offering=offering, teacher=q1_teacher, quarter=1,
    )
    q2_ta = TeachingAssignmentFactory(
        offering=offering, teacher=q2_teacher, quarter=2,
    )
    student = EnrollmentFactory(class_group=class_group).student
    return {
        'year': year, 'offering': offering, 'q1_teacher': q1_teacher,
        'q2_teacher': q2_teacher, 'q1_ta': q1_ta, 'q2_ta': q2_ta,
        'student': student,
    }


@pytest.mark.django_db
def test_one_live_assignment_per_offering_quarter(quarter_world):
    with pytest.raises(IntegrityError), transaction.atomic():
        TeachingAssignmentFactory(
            offering=quarter_world['offering'], teacher=TeacherFactory(), quarter=1,
        )


@pytest.mark.django_db
def test_null_quarter_grants_no_grade_access(quarter_world, authenticated_client):
    teacher = TeacherFactory()
    TeachingAssignmentFactory(
        offering=quarter_world['offering'], teacher=teacher, quarter=None,
    )
    assignment = SubjectAssignmentFactory(
        offering=quarter_world['offering'], quarter=1,
    )
    url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[assignment.pk],
    )
    response = authenticated_client(teacher.user).post(
        url, {'student': quarter_world['student'].pk, 'grade': 8}, format='json',
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_later_teacher_reads_prior_quarter_but_cannot_edit_it(
    quarter_world, authenticated_client,
):
    work = SubjectAssignmentFactory(offering=quarter_world['offering'], quarter=1)
    SubjectGrade.objects.create(
        assignment=work, student=quarter_world['student'], grade=8,
    )
    client = authenticated_client(quarter_world['q2_teacher'].user)
    detail_url = reverse('home-api:subject-assignment-detail', args=[work.pk])
    grade_url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[work.pk],
    )
    assert client.get(detail_url).status_code == 200
    assert client.post(
        grade_url, {'student': quarter_world['student'].pk, 'grade': 9}, format='json',
    ).status_code == 403


@pytest.mark.django_db
def test_earlier_teacher_cannot_read_or_edit_later_quarter(
    quarter_world, authenticated_client,
):
    work = SubjectAssignmentFactory(offering=quarter_world['offering'], quarter=2)
    client = authenticated_client(quarter_world['q1_teacher'].user)
    detail_url = reverse('home-api:subject-assignment-detail', args=[work.pk])
    grade_url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[work.pk],
    )
    assert client.get(detail_url).status_code == 404
    assert client.post(
        grade_url, {'student': quarter_world['student'].pk, 'grade': 8}, format='json',
    ).status_code == 403


@pytest.mark.django_db
def test_exact_quarter_teacher_can_write(quarter_world, authenticated_client):
    work = SubjectAssignmentFactory(offering=quarter_world['offering'], quarter=2)
    url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[work.pk],
    )
    response = authenticated_client(quarter_world['q2_teacher'].user).post(
        url, {'student': quarter_world['student'].pk, 'grade': 8}, format='json',
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_replacing_teacher_in_place_revokes_old_teacher(
    quarter_world, authenticated_client,
):
    replacement = TeacherFactory()
    assignment = quarter_world['q2_ta']
    assignment.teacher = replacement
    assignment.save(update_fields=['teacher'])
    work = SubjectAssignmentFactory(offering=quarter_world['offering'], quarter=2)
    url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[work.pk],
    )
    payload = {'student': quarter_world['student'].pk, 'grade': 8}
    assert authenticated_client(quarter_world['q2_teacher'].user).post(
        url, payload, format='json',
    ).status_code == 403
    assert authenticated_client(replacement.user).post(
        url, payload, format='json',
    ).status_code == 201


@pytest.mark.django_db
def test_archived_year_blocks_exact_quarter_write(
    quarter_world, authenticated_client,
):
    work = SubjectAssignmentFactory(offering=quarter_world['offering'], quarter=1)
    quarter_world['year'].archived = True
    quarter_world['year'].save(update_fields=['archived'])
    url = reverse(
        'home-api:subject-assignment-grade-list-create', args=[work.pk],
    )
    response = authenticated_client(quarter_world['q1_teacher'].user).post(
        url, {'student': quarter_world['student'].pk, 'grade': 8}, format='json',
    )
    assert response.status_code == 403
