"""Spec 0016 — request-scoped authorization for multi-role users."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.request import Request
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.authentication.active_role import ActiveRoleForbidden
from apps.authentication.api.authentication import (
    ActiveRoleSessionAuthentication,
)
from apps.home.models import HomeroomTeacherAssignment
from core.factories import (
    ClassGroupFactory, EnrollmentFactory, ParentFactory, StudentFactory,
    StudentUserFactory,
    SubjectFactory, SubjectOfferingFactory, TeacherFactory, TeacherUserFactory,
)


def add_role(user, group_name):
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)


@pytest.mark.django_db
def test_ac1_valid_assigned_role_is_accepted(authenticated_client):
    user = TeacherUserFactory()

    response = authenticated_client(user, 'teacher').get(
        reverse('auth-api:school-groups'),
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_ac2_role_switching_is_request_local(authenticated_client):
    user = StudentUserFactory()
    add_role(user, 'Admin')
    client = authenticated_client(user)
    url = reverse('home-api:enrollment-list')

    admin_response = client.get(url, HTTP_X_ACTIVE_ROLE='admin')
    student_response = client.get(url, HTTP_X_ACTIVE_ROLE='student')
    admin_again = client.get(url, HTTP_X_ACTIVE_ROLE='admin')

    assert admin_response.status_code == status.HTTP_200_OK
    assert student_response.status_code == status.HTTP_403_FORBIDDEN
    assert admin_again.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_ac3_invalid_role_value_returns_structured_403(authenticated_client):
    response = authenticated_client(TeacherUserFactory()).get(
        reverse('auth-api:school-groups'),
        HTTP_X_ACTIVE_ROLE='homeroom_teacher',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data == {
        'code': 'invalid_active_role',
        'detail': 'X-Active-Role contains an unsupported role.',
    }


@pytest.mark.django_db
def test_ac3_unassigned_role_returns_structured_403(authenticated_client):
    response = authenticated_client(TeacherUserFactory()).get(
        reverse('auth-api:school-groups'),
        HTTP_X_ACTIVE_ROLE='admin',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data == {
        'code': 'active_role_not_assigned',
        'detail': 'The requested active role is not assigned to this user.',
    }


@pytest.mark.django_db
def test_ac4_teacher_maps_to_homeroom_teacher_and_preserves_capability(
    authenticated_client,
):
    teacher = TeacherFactory()
    teacher.user.groups.clear()
    add_role(teacher.user, 'HomeroomTeacher')
    class_group = ClassGroupFactory()
    HomeroomTeacherAssignment.objects.create(
        teacher=teacher, class_group=class_group,
    )

    response = authenticated_client(teacher.user, 'teacher').get(
        reverse('home-api:homeroom-my-class'),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data['class_group_id'] == class_group.id


@pytest.mark.django_db
def test_ac4_teacher_group_does_not_gain_homeroom_capability(
    authenticated_client,
):
    response = authenticated_client(TeacherUserFactory(), 'teacher').get(
        reverse('home-api:homeroom-my-class'),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_ac5_single_role_is_inferred_when_header_is_missing(
    authenticated_client,
):
    response = authenticated_client(TeacherUserFactory()).get(
        reverse('auth-api:school-groups'),
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_ac5_bootstrap_and_public_auth_allow_missing_header(
    authenticated_client,
):
    user = StudentUserFactory()
    add_role(user, 'Admin')
    client = authenticated_client(user)

    me = client.get(reverse('auth-api:current-user'))
    login = client.post(reverse('auth-api:login'), {
        'username': user.username,
        'password': 'testpass123',
    })
    refresh = client.post(reverse('token_refresh'), {
        'refresh': login.data['tokens']['refresh'],
    })
    with patch(
        'apps.authentication.services.AccountService.send_verification_code',
        return_value='signed:code',
    ):
        recovery = client.post(reverse('auth-api:forget-password'), {
            'identifier': user.username,
        })

    assert me.status_code == status.HTTP_200_OK
    assert login.status_code == status.HTTP_200_OK
    assert refresh.status_code == status.HTTP_200_OK
    assert recovery.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_ac6_multi_role_request_without_header_is_403(authenticated_client):
    user = StudentUserFactory()
    add_role(user, 'Admin')

    response = authenticated_client(user).get(
        reverse('auth-api:school-groups'),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data['code'] == 'active_role_required'


@pytest.mark.django_db
def test_ac7_inactive_admin_role_does_not_widen_student_queryset(
    authenticated_client,
):
    student = StudentFactory()
    add_role(student.user, 'Admin')
    class_group = ClassGroupFactory()
    EnrollmentFactory(student=student, class_group=class_group)
    visible = SubjectFactory(name='Visible subject')
    hidden = SubjectFactory(name='Admin-only subject')
    SubjectOfferingFactory(subject=visible, class_group=class_group)
    client = authenticated_client(student.user)
    url = reverse('home-api:subject-list')

    student_response = client.get(url, HTTP_X_ACTIVE_ROLE='student')
    admin_response = client.get(url, HTTP_X_ACTIVE_ROLE='admin')

    student_ids = {row['id'] for row in student_response.data['results']}
    admin_ids = {row['id'] for row in admin_response.data['results']}
    assert student_ids == {visible.id}
    assert {visible.id, hidden.id} <= admin_ids


@pytest.mark.django_db
def test_ac7_inactive_admin_role_does_not_widen_student_list(
    authenticated_client,
):
    student = StudentFactory()
    add_role(student.user, 'Admin')
    class_group = ClassGroupFactory()
    EnrollmentFactory(student=student, class_group=class_group)
    classmate = EnrollmentFactory(class_group=class_group).student
    client = authenticated_client(student.user)
    url = reverse('home-api:student-list')

    student_response = client.get(url, HTTP_X_ACTIVE_ROLE='student')
    admin_response = client.get(url, HTTP_X_ACTIVE_ROLE='admin')

    assert student_response.status_code == status.HTTP_200_OK
    assert admin_response.status_code == status.HTTP_200_OK
    student_ids = {row['id'] for row in student_response.data['results']}
    admin_ids = {row['id'] for row in admin_response.data['results']}
    assert student_ids == {student.id}
    assert {student.id, classmate.id} <= admin_ids


@pytest.mark.django_db
def test_ac7_inactive_teacher_role_does_not_widen_parent_student_list(
    authenticated_client,
):
    teacher = TeacherFactory()
    add_role(teacher.user, 'Parent')
    parent = ParentFactory(user=teacher.user)
    class_group = ClassGroupFactory()
    child = EnrollmentFactory(class_group=class_group).student
    other = EnrollmentFactory(class_group=class_group).student
    parent.students.add(child)
    client = authenticated_client(teacher.user)
    url = reverse('home-api:student-list')

    parent_response = client.get(url, HTTP_X_ACTIVE_ROLE='parent')
    teacher_response = client.get(url, HTTP_X_ACTIVE_ROLE='teacher')

    assert parent_response.status_code == status.HTTP_200_OK
    assert teacher_response.status_code == status.HTTP_200_OK
    parent_ids = {row['id'] for row in parent_response.data['results']}
    teacher_ids = {row['id'] for row in teacher_response.data['results']}
    assert parent_ids == {child.id}
    assert {child.id, other.id} <= teacher_ids


@pytest.mark.django_db
def test_ac7_session_authentication_uses_the_same_role_validation():
    user = TeacherUserFactory()
    factory = APIRequestFactory()
    authenticator = ActiveRoleSessionAuthentication()

    valid = factory.get('/api/v1/school-groups/', HTTP_X_ACTIVE_ROLE='teacher')
    valid.user = user
    request = Request(valid)
    authenticated_user, _ = authenticator.authenticate(request)

    assert authenticated_user == user
    assert request.active_role == 'teacher'

    invalid = factory.get('/api/v1/school-groups/', HTTP_X_ACTIVE_ROLE='admin')
    invalid.user = user
    with pytest.raises(ActiveRoleForbidden) as exc:
        authenticator.authenticate(Request(invalid))
    assert exc.value.detail['code'] == 'active_role_not_assigned'


def test_ac8_cors_allows_active_role_header(settings):
    assert 'x-active-role' in settings.CORS_ALLOW_HEADERS
