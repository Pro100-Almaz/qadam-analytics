"""Spec 0014 — users and schools: AC-6, AC-15."""

import pytest
from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist
from django.test import RequestFactory
from django.urls import get_resolver, reverse
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import CustomUser, School
from core.factories import SchoolFactory, StudentFactory, UserFactory
from core.soft_delete import is_soft_deletable

pytestmark = pytest.mark.django_db

PASSWORD = 'testpass123'


def test_ac6_deleted_user_cannot_authenticate(client, api_client):
    user = StudentFactory().user
    refresh = RefreshToken.for_user(user)
    access = str(refresh.access_token)
    me_url = reverse('auth-api:current-user')
    login_url = reverse('auth-api:login')

    # Everything works while the user is live...
    assert api_client.post(login_url, {'username': user.username, 'password': PASSWORD}).status_code == 200
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
    assert api_client.get(me_url).status_code == 200
    api_client.credentials()

    user.delete()

    # ...and nothing does once they are soft-deleted.
    assert client.login(username=user.username, password=PASSWORD) is False
    assert api_client.post(login_url, {'username': user.username, 'password': PASSWORD}).status_code == 400
    refreshed = api_client.post(reverse('token_refresh'), {'refresh': str(refresh)})
    assert refreshed.status_code == 401
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
    assert api_client.get(me_url).status_code == 401

    assert not CustomUser.objects.filter(pk=user.pk).exists()
    assert not CustomUser.in_school.filter(pk=user.pk).exists()


def test_ac6_username_of_deleted_user_can_log_in_as_the_new_user(api_client):
    old = UserFactory(username='reused')
    old.delete()
    new = UserFactory(username='reused')

    response = api_client.post(
        reverse('auth-api:login'), {'username': 'reused', 'password': PASSWORD},
    )

    assert response.status_code == 200
    assert response.data['user']['id'] == new.pk


@pytest.fixture
def superuser_client(client):
    school = SchoolFactory()
    root = UserFactory(school=school, username='root', is_superuser=True, is_staff=True)
    client.post(
        reverse('admin:login'),
        {'username': root.username, 'password': PASSWORD, 'next': '/admin/'},
    )
    return client, root


def test_ac15_school_cannot_be_deleted_in_app(superuser_client):
    client, root = superuser_client
    empty = SchoolFactory(slug='empty_school')

    # The admin: no delete page, no bulk action — not even for an empty
    # school, not even for a superuser.
    response = client.get(reverse('admin:authentication_school_delete', args=[empty.pk]))
    assert response.status_code == 403
    response = client.post(reverse('admin:authentication_school_delete', args=[empty.pk]), {'post': 'yes'})
    assert response.status_code == 403
    request = RequestFactory().get('/admin/authentication/school/')
    request.user = root
    assert 'delete_selected' not in admin.site._registry[School].get_actions(request)
    assert School.objects.filter(pk=empty.pk).exists()

    # Not soft-deletable either: nothing to hide it with.
    assert not is_soft_deletable(School)
    with pytest.raises(FieldDoesNotExist):
        School._meta.get_field('is_deleted')

    # And no API view is bound to School at all, so none can delete one.
    for view in _api_view_classes():
        assert _model_of(view) is not School, view


def _api_view_classes():
    def walk(patterns, prefix=''):
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if hasattr(pattern, 'url_patterns'):
                yield from walk(pattern.url_patterns, route)
            elif route.startswith('api/'):
                view = getattr(pattern.callback, 'cls', None) or getattr(pattern.callback, 'view_class', None)
                if view is not None:
                    yield view
    return set(walk(get_resolver().url_patterns))


def _model_of(view):
    queryset = getattr(view, 'queryset', None)
    if queryset is not None:
        return queryset.model
    serializer = getattr(view, 'serializer_class', None)
    meta = getattr(serializer, 'Meta', None)
    return getattr(meta, 'model', None)
