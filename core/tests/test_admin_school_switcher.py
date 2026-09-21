"""The admin acts in exactly one school, and the header says which.

`/admin/` used to resolve superusers to the cross-school sentinel, so every
changelist was a union of both tenants. These pin the replacement: the header
switcher names one school, everything on the page is that school's, and the
ways a second school could leak back in — the unscoped `CustomUser` manager, a
`school` FK picker offering every tenant, a stale session value — each stay
shut.

The switcher is a view selector, not a permission: a superuser may still pick
any school. What it buys is that every page has an unambiguous answer to "which
tenant am I in", which is what row stamping and the active-year lookups need.
"""

import re

import pytest
from django.urls import reverse

from apps.authentication.school_selection import SESSION_KEY
from apps.home.models import Subject
from core.factories import SchoolFactory, UserFactory
from core.tenancy import school_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def school_a(db):
    return SchoolFactory(slug='school_a', name='Alpha School')


@pytest.fixture
def school_b(db):
    return SchoolFactory(slug='school_b', name='Beta School')


@pytest.fixture
def superuser(school_a):
    return UserFactory(
        school=school_a, username='root', is_superuser=True, is_staff=True,
    )


@pytest.fixture
def admin_client(client, superuser):
    # Logging in through the view, not client.force_login: the user_logged_in
    # signal posts a message, which needs MessageMiddleware in the stack.
    client.post(
        reverse('admin:login'),
        {'username': superuser.username, 'password': 'testpass123', 'next': '/admin/'},
    )
    return client


@pytest.fixture
def staff_client(client, school_a):
    """A staff member who is NOT a superuser — the switcher is not for them."""
    staff = UserFactory(
        school=school_a, username='staffer', is_staff=True, is_superuser=False,
    )
    client.post(
        reverse('admin:login'),
        {'username': staff.username, 'password': 'testpass123', 'next': '/admin/'},
    )
    return client


@pytest.fixture
def two_subjects(school_a, school_b):
    with school_scope(school_a):
        a = Subject.objects.create(name='Alpha Algebra', school=school_a)
    with school_scope(school_b):
        b = Subject.objects.create(name='Beta Biology', school=school_b)
    return a, b


def _switcher(body):
    """The switcher form's HTML, or None when the page does not offer one."""
    match = re.search(r'<form id="school-switcher".*?</form>', body, re.S)
    return match.group(0) if match else None


def _selected_school_pk(body):
    """The pk of the `<option ... selected>` in the switcher, or None."""
    form = _switcher(body) or ''
    match = re.search(r'<option value="(\d+)"\s*\n?\s*selected', form)
    return int(match.group(1)) if match else None


def _option_values(body, field_name):
    """The `<option>` values of one named form field."""
    match = re.search(
        rf'<select name="{field_name}"[^>]*>(.*?)</select>', body, re.S,
    )
    return re.findall(r'<option value="(\d*)"', match.group(1)) if match else []


def _switch(client, school, follow=False):
    return client.post(
        reverse('admin:switch_school'), {'active_school': school.pk}, follow=follow,
    )


# ── the header ───────────────────────────────────────────────────────────────

def test_the_header_offers_every_school_and_preselects_the_active_one(
    admin_client, school_a, school_b,
):
    body = admin_client.get(reverse('admin:index')).content.decode()

    assert _switcher(body) is not None
    assert school_a.name in body and school_b.name in body
    assert _selected_school_pk(body) == school_a.pk


def test_a_staff_non_superuser_gets_no_switcher(staff_client):
    body = staff_client.get(reverse('admin:index')).content.decode()
    assert _switcher(body) is None


# ── switching ────────────────────────────────────────────────────────────────

def test_switching_changes_what_the_changelist_shows(
    admin_client, school_b, two_subjects,
):
    subject_a, subject_b = two_subjects
    url = reverse('admin:home_subject_changelist')

    body = admin_client.get(url).content.decode()
    assert subject_a.name in body and subject_b.name not in body

    _switch(admin_client, school_b)

    body = admin_client.get(url).content.decode()
    assert subject_b.name in body and subject_a.name not in body


def test_the_choice_survives_the_next_request(admin_client, school_b):
    _switch(admin_client, school_b)
    admin_client.get(reverse('admin:index'))
    assert admin_client.session[SESSION_KEY] == school_b.pk


def test_a_get_is_refused(admin_client):
    assert admin_client.get(reverse('admin:switch_school')).status_code == 405


def test_an_unknown_school_is_ignored(admin_client):
    admin_client.post(reverse('admin:switch_school'), {'active_school': 999999})
    assert SESSION_KEY not in admin_client.session


def test_a_non_superuser_cannot_switch_by_posting(staff_client, school_b):
    """403, not a bounce to LOGIN_URL — that route retired with the HTML layer."""
    response = staff_client.post(
        reverse('admin:switch_school'), {'active_school': school_b.pk},
    )
    assert response.status_code == 403
    assert staff_client.session.get(SESSION_KEY) is None


# A POST field is not a safe redirect target: an open redirect here would be a
# phishing primitive on a URL that looks like the customer's own admin.
@pytest.mark.parametrize('hostile', [
    'https://evil.example/pwn',      # absolute
    '//evil.example/pwn',            # protocol-relative
    '/admin/../pages/dashboard/',    # normalises out of the admin
    '/pages/dashboard/',             # plainly elsewhere
])
def test_a_hostile_next_is_not_followed(admin_client, school_b, hostile):
    response = admin_client.post(
        reverse('admin:switch_school'),
        {'active_school': school_b.pk, 'next': hostile},
    )
    assert response['Location'] == reverse('admin:index')


def test_a_changelist_filter_survives_the_switch(admin_client, school_b):
    """The query string is what makes switching usable mid-investigation."""
    target = reverse('admin:home_subject_changelist') + '?status__exact=active'
    response = admin_client.post(
        reverse('admin:switch_school'), {'active_school': school_b.pk, 'next': target},
    )
    assert response['Location'] == target


def test_next_inside_the_admin_is_followed(admin_client, school_b):
    target = reverse('admin:home_subject_changelist')
    response = admin_client.post(
        reverse('admin:switch_school'), {'active_school': school_b.pk, 'next': target},
    )
    assert response['Location'] == target


# ── the leaks the switcher would otherwise still have ────────────────────────

def test_the_user_changelist_is_scoped_despite_the_unscoped_manager(
    admin_client, school_a, school_b,
):
    """`CustomUser.objects` is global by design, so this is the one changelist
    that does not narrow through the default manager."""
    here = UserFactory(school=school_a, username='alpha_person')
    there = UserFactory(school=school_b, username='beta_person')

    body = admin_client.get(reverse('admin:authentication_customuser_changelist')).content.decode()
    assert here.username in body
    assert there.username not in body


def test_a_user_from_another_school_is_not_reachable_by_pk(admin_client, school_b):
    there = UserFactory(school=school_b, username='beta_person')
    url = reverse('admin:authentication_customuser_change', args=[there.pk])
    assert admin_client.get(url).status_code == 302   # admin's "does not exist" redirect


def test_a_user_picker_offers_only_the_active_schools_people(
    admin_client, school_a, school_b,
):
    here = UserFactory(school=school_a, username='alpha_person')
    there = UserFactory(school=school_b, username='beta_person')

    body = admin_client.get(reverse('admin:home_subject_add')).content.decode()
    offered = _option_values(body, 'added_by')   # `Subject.added_by`

    assert str(here.pk) in offered
    assert str(there.pk) not in offered


def test_the_school_picker_offers_only_the_active_school(
    admin_client, school_a, school_b,
):
    """Otherwise the add form is a second, contradictory school selector."""
    body = admin_client.get(reverse('admin:home_subject_add')).content.decode()

    assert _option_values(body, 'school') == [str(school_a.pk)]


def test_a_row_created_after_switching_lands_in_the_switched_school(
    admin_client, school_a, school_b,
):
    """The bug the switcher exists to kill: `save_model` used to fall back to
    the acting user's own school, so browsing B and clicking Add wrote to A."""
    _switch(admin_client, school_b)

    admin_client.post(reverse('admin:home_subject_add'), {
        'name': 'Made While Switched',
        'language_group': 'kaz',
        'status': 'active',
        'school': school_b.pk,
    })

    with school_scope(school_b):
        created = Subject.objects.get(name='Made While Switched')
    assert created.school_id == school_b.pk


def test_every_model_admin_is_scoped_even_without_the_mixin():
    """Registration injects it, so a new ModelAdmin cannot forget."""
    from django.contrib import admin

    from core.admin_mixins import SchoolScopedAdminMixin

    unscoped = [
        model._meta.label
        for model, model_admin in admin.site._registry.items()
        if not isinstance(model_admin, SchoolScopedAdminMixin)
    ]
    assert unscoped == []
