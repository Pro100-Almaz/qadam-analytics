"""Access control for a single report.

Regression cover for `permission_classes = [CanAccessStudent]` on the detail
view, which passed the StudentReport itself to can_access_student(). Teachers
and students got a 500 (`'StudentReport' object has no attribute
'get_current_enrollment'`), and a parent's children were matched against the
report's pk instead of the student's.
"""

import pytest
from rest_framework.test import APIClient

from apps.home.models import AcademicYear
from apps.student_report.models import StudentReport
from core.factories import StudentFactory


def _report(student):
    return StudentReport.objects.create(
        student=student,
        academic_year=AcademicYear.objects.get(is_active=True),
        quarter=1,
    )


def _url(report):
    return f'/api/v1/reports/{report.pk}/'


@pytest.mark.django_db
def test_anonymous_is_rejected(student):
    report = _report(student)
    assert APIClient().get(_url(report)).status_code in (401, 403)


@pytest.mark.django_db
def test_teacher_can_read_report(authenticated_client, teacher, student):
    report = _report(student)
    response = authenticated_client(teacher.user).get(_url(report))
    assert response.status_code == 200


@pytest.mark.django_db
def test_student_can_read_own_report(authenticated_client, student):
    report = _report(student)
    response = authenticated_client(student.user).get(_url(report))
    assert response.status_code == 200


@pytest.mark.django_db
def test_student_cannot_read_another_students_report(authenticated_client, student):
    report = _report(StudentFactory())
    response = authenticated_client(student.user).get(_url(report))
    assert response.status_code == 403


@pytest.mark.django_db
def test_parent_can_read_own_childs_report(authenticated_client, parent, student):
    parent.students.add(student)
    report = _report(student)
    response = authenticated_client(parent.user).get(_url(report))
    assert response.status_code == 200


@pytest.mark.django_db
def test_parent_cannot_read_other_childs_report(authenticated_client, parent, student):
    parent.students.add(student)
    report = _report(StudentFactory())
    response = authenticated_client(parent.user).get(_url(report))
    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_read_any_report(authenticated_client, admin_user, student):
    report = _report(student)
    response = authenticated_client(admin_user).get(_url(report))
    assert response.status_code == 200
