"""The admin must not be able to write a user with no school.

`school` was absent from CustomUserAdmin.add_fieldsets, so "Add user" wrote
school=NULL on a non-superuser and Postgres rejected it with the
`user_has_school_unless_superuser` check constraint — a 500. The change form
had the field but let it be blanked, with the same result.

The forms are exercised through ModelAdmin.get_form(), which is how the admin
builds them: it runs modelform_factory over the declared fieldsets, so this is
also what proves `school` is on the add form at all.
"""

import pytest
from django.contrib import admin as django_admin
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from apps.authentication.models import CustomUser
from core.factories import SchoolFactory, UserFactory


@pytest.fixture
def school(db):
    """The school the surrounding scope names.

    Not a second tenant: since the admin switcher landed, the `school` picker
    is pinned to the active school, so a form offered another school's pk now
    correctly refuses it — see `test_the_form_refuses_another_schools_pk`.
    """
    from core.factories import DEFAULT_TEST_SCHOOL_SLUG
    return SchoolFactory(slug=DEFAULT_TEST_SCHOOL_SLUG)


@pytest.fixture
def user_admin():
    return django_admin.site._registry[CustomUser]


@pytest.fixture
def request_(rf: RequestFactory):
    request = rf.get('/admin/authentication/customuser/')
    request.user = AnonymousUser()
    return request


def _form_class(user_admin, request_, obj=None):
    return user_admin.get_form(request_, obj)


@pytest.mark.django_db
def test_school_is_on_the_add_form(user_admin, request_):
    assert 'school' in _form_class(user_admin, request_)().fields


@pytest.mark.django_db
def test_add_form_rejects_a_user_with_no_school(user_admin, request_):
    form = _form_class(user_admin, request_)(data={
        'username': 'nobody@test.kz',
        'password1': 'Qadam2026*', 'password2': 'Qadam2026*',
    })

    assert not form.is_valid()
    assert 'school' in form.errors


@pytest.mark.django_db
def test_add_form_accepts_a_user_with_a_school(user_admin, request_, school):
    form = _form_class(user_admin, request_)(data={
        'username': 'somebody@test.kz',
        'password1': 'Qadam2026*', 'password2': 'Qadam2026*',
        'school': school.pk,
    })

    assert form.is_valid(), form.errors
    assert form.save().school_id == school.pk


@pytest.mark.django_db
def test_the_form_refuses_another_schools_pk(user_admin, request_, school):
    """The picker is pinned to the active school, so this is not a valid choice.

    Belt and braces with the switcher: even a hand-crafted POST naming another
    tenant is a field error rather than a cross-school write.
    """
    elsewhere = SchoolFactory(slug='school_elsewhere')
    form = _form_class(user_admin, request_)(data={
        'username': 'somebody@test.kz',
        'password1': 'Qadam2026*', 'password2': 'Qadam2026*',
        'school': elsewhere.pk,
    })

    assert not form.is_valid()
    assert 'school' in form.errors


def _change_data(user, **over):
    data = {
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'avatar': '',
        'school': str(user.school_id or ''),
        'date_joined_0': user.date_joined.date().isoformat(),
        'date_joined_1': user.date_joined.time().isoformat(),
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_change_form_rejects_blanking_the_school(user_admin, request_, school):
    user = UserFactory(school=school)
    form_class = _form_class(user_admin, request_, user)

    form = form_class(data=_change_data(user, school=''), instance=user)

    assert not form.is_valid()
    assert 'school' in form.errors


@pytest.mark.django_db
def test_change_form_allows_a_superuser_without_a_school(user_admin, request_, school):
    user = UserFactory(school=school, is_superuser=True)
    form_class = _form_class(user_admin, request_, user)

    form = form_class(
        data=_change_data(user, school='', is_superuser='on', is_active='on'),
        instance=user,
    )

    assert form.is_valid(), form.errors
    assert form.save().school_id is None
