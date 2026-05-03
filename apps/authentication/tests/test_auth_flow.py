import pytest
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status

from core.factories import (
    UserFactory, StudentUserFactory, TeacherUserFactory, AdminUserFactory,
    StudentFactory, SchoolGroupFactory, AcademicYearFactory,
)


@pytest.mark.django_db
class TestLoginFlow:

    def test_valid_login_returns_tokens_and_user(self, api_client):
        user = TeacherUserFactory()
        response = api_client.post(reverse('auth-api:login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        assert response.status_code == status.HTTP_200_OK
        assert 'tokens' in response.data
        assert 'access' in response.data['tokens']
        assert 'refresh' in response.data['tokens']
        assert 'user' in response.data

    def test_wrong_password_returns_400(self, api_client):
        user = UserFactory()
        response = api_client.post(reverse('auth-api:login'), {
            'username': user.username,
            'password': 'wrongpassword',
        })
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_user_returns_400(self, api_client):
        response = api_client.post(reverse('auth-api:login'), {
            'username': 'ghost',
            'password': 'whatever',
        })
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_login_throttle_after_5_attempts(self, api_client):
        for i in range(6):
            response = api_client.post(reverse('auth-api:login'), {
                'username': 'ghost',
                'password': 'wrong',
            })
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
class TestTokenRefresh:

    def test_valid_refresh_returns_new_access(self, api_client):
        user = UserFactory()
        login_resp = api_client.post(reverse('auth-api:login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        refresh = login_resp.data['tokens']['refresh']
        response = api_client.post(reverse('token_refresh'), {
            'refresh': refresh,
        })
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data

    def test_blacklisted_refresh_token_rejected(self, api_client):
        user = UserFactory()
        login_resp = api_client.post(reverse('auth-api:login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        tokens = login_resp.data['tokens']
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        api_client.post(reverse('auth-api:logout'), {'refresh': tokens['refresh']})
        api_client.credentials()
        response = api_client.post(reverse('token_refresh'), {
            'refresh': tokens['refresh'],
        })
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestLogout:

    def test_logout_blacklists_refresh_token(self, api_client):
        user = UserFactory()
        login_resp = api_client.post(reverse('auth-api:login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        tokens = login_resp.data['tokens']
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = api_client.post(reverse('auth-api:logout'), {
            'refresh': tokens['refresh'],
        })
        assert response.status_code == status.HTTP_205_RESET_CONTENT

    def test_logout_without_refresh_returns_400(self, authenticated_client):
        user = UserFactory()
        client = authenticated_client(user)
        response = client.post(reverse('auth-api:logout'), {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestRegister:

    def test_admin_can_register_student(self, authenticated_client):
        admin = AdminUserFactory()
        client = authenticated_client(admin)
        AcademicYearFactory(is_active=True)
        sg = SchoolGroupFactory()
        response = client.post(
            reverse('auth-api:register'),
            {
                'first_name': 'Test',
                'last_name': 'Student',
                'email': 'newstudent@test.kz',
                'password1': 'Str0ngP@ss!',
                'password2': 'Str0ngP@ss!',
                'role': 'Student',
                'school_group': sg.pk,
            },
            format='multipart',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert 'user' in response.data

    def test_non_admin_cannot_register(self, authenticated_client):
        user = TeacherUserFactory()
        client = authenticated_client(user)
        response = client.post(
            reverse('auth-api:register'),
            {
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'test@test.kz',
                'password1': 'testpass123',
                'password2': 'testpass123',
                'role': 'Student',
            },
            format='multipart',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_cannot_register(self, api_client):
        response = api_client.post(
            reverse('auth-api:register'),
            {
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'test@test.kz',
                'password1': 'testpass123',
                'password2': 'testpass123',
                'role': 'Student',
            },
            format='multipart',
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestPasswordResetFlow:

    @patch('apps.authentication.services.AccountService.send_verification_code')
    def test_forget_password_does_not_leak_code(self, mock_send, api_client):
        user = UserFactory()
        mock_send.return_value = 'signed:code'
        response = api_client.post(reverse('auth-api:forget-password'), {
            'username': user.username,
        })
        assert response.status_code == status.HTTP_200_OK
        assert 'signed_code' not in response.data
        assert 'code' not in response.data
        assert response.data['message'] == 'Verification code sent'

    def test_forget_password_unknown_user(self, api_client):
        response = api_client.post(reverse('auth-api:forget-password'), {
            'username': 'nonexistent',
        })
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch('apps.authentication.services.AccountService.send_verification_code')
    def test_verify_code_429_after_5_bad_attempts(self, mock_send, api_client):
        from django.core.cache import cache
        user = UserFactory()
        cache_key = f'pwd_reset:{user.username}'
        cache.set(cache_key, {'signed_code': 'test:signed', 'attempts': 5}, timeout=600)

        response = api_client.post(reverse('auth-api:verify-code'), {
            'username': user.username,
            'verification_code': '000000',
        })
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    @patch('apps.authentication.services.AccountService.check_verification_code')
    @patch('apps.authentication.services.AccountService.send_verification_code')
    def test_full_reset_flow(self, mock_send, mock_check, api_client):
        from django.core.cache import cache
        user = UserFactory()
        mock_send.return_value = 'signed:code'
        mock_check.return_value = (True, None)

        api_client.post(reverse('auth-api:forget-password'), {
            'username': user.username,
        })

        response = api_client.post(reverse('auth-api:verify-code'), {
            'username': user.username,
            'verification_code': '123456',
        })
        assert response.status_code == status.HTTP_200_OK
        assert response.data['verified'] is True
        token = response.data['token']

        response = api_client.post(reverse('auth-api:change-password'), {
            'token': token,
            'password1': 'NewStr0ng!Pass',
            'password2': 'NewStr0ng!Pass',
        })
        assert response.status_code == status.HTTP_200_OK

    def test_change_password_invalid_token(self, api_client):
        response = api_client.post(reverse('auth-api:change-password'), {
            'token': 'bogus:token',
            'password1': 'NewStr0ng!Pass',
            'password2': 'NewStr0ng!Pass',
        })
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCurrentUser:

    def test_get_current_user(self, authenticated_client):
        user = UserFactory()
        client = authenticated_client(user)
        response = client.get(reverse('auth-api:current-user'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == user.pk

    def test_unauthenticated_cannot_get_me(self, api_client):
        response = api_client.get(reverse('auth-api:current-user'))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestSchoolGroups:

    def test_school_groups_list_returns_only_id_and_name(self, api_client):
        SchoolGroupFactory(name='Group A', color='#FF0000')
        response = api_client.get(reverse('auth-api:school-groups'))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        item = response.data[0]
        assert set(item.keys()) == {'id', 'name'}
        assert 'color' not in item
        assert 'avatar' not in item
