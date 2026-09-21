"""Access control for the per-student report list.

Regression cover for a hole where `permission_classes = [CanAccessStudent]`
replaced the IsAuthenticated default with a permission class that only defines
has_object_permission — which a ListAPIView never invokes. The endpoint served
any student's reports to anonymous callers.
"""

import pytest
from rest_framework.test import APIClient

from core.factories import StudentFactory


def _url(student):
    return f'/api/v1/students/{student.pk}/reports/'


@pytest.mark.django_db
def test_anonymous_is_rejected():
    student = StudentFactory()
    assert APIClient().get(_url(student)).status_code in (401, 403)


@pytest.mark.django_db
def test_student_cannot_read_another_students_reports(authenticated_client, student):
    other = StudentFactory()
    response = authenticated_client(student.user).get(_url(other))
    assert response.status_code == 403


@pytest.mark.django_db
def test_student_can_read_own_reports(authenticated_client, student):
    response = authenticated_client(student.user).get(_url(student))
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_can_read_any_students_reports(authenticated_client, admin_user, student):
    response = authenticated_client(admin_user).get(_url(student))
    assert response.status_code == 200
