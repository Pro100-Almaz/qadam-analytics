"""Registration must not let an admin place a user in another school.

`school` used to be accepted straight from the request body, so an admin of
one school could mint users in the other. It is now server-assigned from the
creating admin; only a superuser may name a school explicitly.
"""

import pytest

from apps.authentication.models import CustomUser
from core.factories import AdminUserFactory, SchoolFactory

URL = '/api/v1/auth/register/'


@pytest.fixture
def schools(db):
    return SchoolFactory(slug='school_a'), SchoolFactory(slug='school_b')


def _payload(**over):
    data = {
        'first_name': 'New', 'last_name': 'User',
        'email': 'new.user@test.kz',
        'password1': 'Qadam2026*', 'password2': 'Qadam2026*',
        'role': CustomUser.GROUP_TEACHER,
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_admin_cannot_register_user_into_another_school(authenticated_client, schools):
    own, other = schools
    admin = AdminUserFactory(school=own)

    response = authenticated_client(admin).post(
        URL, _payload(school=str(other.uuid)), format='multipart',
    )

    assert response.status_code == 201
    created = CustomUser.objects.get(email='new.user@test.kz')
    assert created.school_id == own.pk, 'client-supplied school was honoured'


@pytest.mark.django_db
def test_superuser_may_name_the_school(authenticated_client, schools):
    own, other = schools
    root = AdminUserFactory(school=own, is_superuser=True)

    response = authenticated_client(root).post(
        URL, _payload(school=str(other.uuid)), format='multipart',
    )

    assert response.status_code == 201
    assert CustomUser.objects.get(email='new.user@test.kz').school_id == other.pk
