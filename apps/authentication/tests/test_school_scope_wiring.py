"""How a request gets its school: the middleware and the DRF auth class.

These two are the whole of phase 3's isolation wiring. Between them they
implement the rule that **no request ever resolves to `ALL`**: in `/admin/` a
superuser acts in the one school the header switcher names, and everywhere else
every user gets their own. That is a security boundary, so it is pinned from
both sides — what each surface grants, and what it refuses.
"""

import jwt
import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.api.authentication import resolve_scope
from core.factories import AdminUserFactory, SchoolFactory, UserFactory
from core.middleware import SchoolScopeMiddleware
from core.tenancy import UNSET, get_active_school

pytestmark = pytest.mark.django_db


@pytest.fixture
def school_a(db):
    return SchoolFactory(slug='school_a')


@pytest.fixture
def school_b(db):
    return SchoolFactory(slug='school_b')


def _scope_for(user, path='/api/v1/students/', session=None):
    """Run the middleware over one request and report the scope it set."""
    seen = {}

    def get_response(request):
        seen['scope'] = get_active_school()
        return 'response'

    request = RequestFactory().get(path)
    request.user = user
    request.session = session if session is not None else {}
    SchoolScopeMiddleware(get_response)(request)
    return seen['scope']


# ── middleware: who gets what ────────────────────────────────────────────────

def test_anonymous_gets_no_scope_at_all():
    """Fail closed. UNSET raises under 'enforce' rather than leaking."""
    assert _scope_for(AnonymousUser()) is UNSET


def test_a_regular_user_gets_their_own_school(school_a):
    user = AdminUserFactory(school=school_a)
    assert _scope_for(user) == school_a.pk


def test_a_superuser_in_the_admin_gets_one_school_not_every_school(school_a, school_b):
    """The switcher's whole point: /admin/ names a tenant, it never unions them.

    `ALL` used to be the answer here, which made every changelist a mix of both
    schools and left `save_model` with no school to stamp on a new row.
    """
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert _scope_for(user, path='/admin/home/subject/') == school_a.pk


def test_a_superuser_outside_the_admin_gets_only_their_own_school(school_a):
    """The §4 decision, and the reason it is path-based rather than role-based.

    A superuser holding an admin session cookie and hitting the API still gets
    their own school — so a mistyped cross-school id 404s instead of silently
    landing in another tenant. Cross-school work happens where it is visible.
    """
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert _scope_for(user, path='/api/v1/students/') == school_a.pk


def test_the_admin_switcher_narrows_a_superuser_to_the_chosen_school(school_a, school_b):
    """The session key the header switcher writes."""
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    scope = _scope_for(
        user, path='/admin/', session={'active_school_id': school_b.pk},
    )
    assert scope == school_b.pk


def test_a_stale_session_choice_falls_back_instead_of_resolving(school_a):
    """Validated on read, not only on the POST that set it.

    A session outlives the school it names — deleted, or the account demoted
    out of being able to select it. The value must not resolve into a scope
    just because it is present.
    """
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    gone = SchoolFactory(slug='school_gone')
    gone_pk = gone.pk
    gone.delete()

    assert _scope_for(
        user, path='/admin/', session={'active_school_id': gone_pk},
    ) == school_a.pk


def test_a_junk_session_choice_falls_back_instead_of_raising(school_a):
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert _scope_for(
        user, path='/admin/', session={'active_school_id': 'not-a-pk'},
    ) == school_a.pk


def test_a_non_superuser_cannot_switch_school_through_the_session(school_a, school_b):
    """The session key is only read for superusers — the switcher is not a grant."""
    user = AdminUserFactory(school=school_a)
    scope = _scope_for(
        user, path='/admin/', session={'active_school_id': school_b.pk},
    )
    assert scope == school_a.pk


def test_a_schoolless_superuser_in_the_admin_lands_on_a_real_school(school_a):
    """`createsuperuser` leaves no school, and the admin is where they fix it.

    Failing closed here would lock the only account able to assign itself a
    school out of the page that assigns it. *Which* school it lands on is
    deliberately not asserted — it is the first by name, which depends on what
    rows exist — only that it is one concrete tenant rather than no scope.
    """
    from apps.authentication.models import School

    user = UserFactory(school=None, is_superuser=True, is_staff=True)
    scope = _scope_for(user, path='/admin/')

    assert scope is not UNSET
    assert scope in set(School.objects.values_list('pk', flat=True))


def test_a_schoolless_superuser_can_still_switch(school_a):
    """And the switcher gets them out of whichever one they landed on."""
    user = UserFactory(school=None, is_superuser=True, is_staff=True)
    scope = _scope_for(
        user, path='/admin/', session={'active_school_id': school_a.pk},
    )
    assert scope == school_a.pk


def test_a_schoolless_superuser_outside_the_admin_fails_closed():
    """The last path that used to widen to ALL. It no longer does."""
    user = UserFactory(school=None, is_superuser=True, is_staff=True)
    assert _scope_for(user, path='/api/v1/students/') is UNSET


def test_the_scope_is_reset_after_the_response(school_a):
    """A gunicorn worker thread reuses its context between requests."""
    user = AdminUserFactory(school=school_a)
    assert get_active_school() is not None
    before = get_active_school()
    _scope_for(user)
    assert get_active_school() == before


def test_the_scope_is_reset_even_when_the_view_raises(school_a):
    user = AdminUserFactory(school=school_a)
    before = get_active_school()

    def boom(request):
        raise RuntimeError('view exploded')

    request = RequestFactory().get('/api/v1/students/')
    request.user = user
    request.session = {}
    with pytest.raises(RuntimeError):
        SchoolScopeMiddleware(boom)(request)
    assert get_active_school() == before


# ── the DRF auth class: the claim is a tripwire, not the grant ───────────────

def test_a_matching_claim_resolves_to_the_users_school(school_a):
    from apps.authentication.school_cache import uuid_for_school_pk
    user = AdminUserFactory(school=school_a)
    assert resolve_scope(user, uuid_for_school_pk(school_a.pk)) == school_a.pk


def test_a_token_with_no_claim_still_resolves(school_a):
    """The grant is user.school_id; the claim is only checked when present."""
    user = AdminUserFactory(school=school_a)
    assert resolve_scope(user, None) == school_a.pk


def test_a_mismatched_claim_is_rejected(school_a, school_b):
    """A token minted before the user moved schools must not assert the old one.

    This is what removes the staleness window: REFRESH_TOKEN_LIFETIME is 7 days,
    so without the check a moved or offboarded user would keep their old school
    for a week.
    """
    from apps.authentication.school_cache import uuid_for_school_pk
    user = AdminUserFactory(school=school_a)
    with pytest.raises(AuthenticationFailed, match='does not match'):
        resolve_scope(user, uuid_for_school_pk(school_b.pk))


def test_a_superuser_over_the_api_is_not_special(school_a):
    """No token resolves to anything wider than the user's own school."""
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert resolve_scope(user, None) == school_a.pk


def test_a_schoolless_superuser_is_refused_over_the_api():
    """The DRF half of the ALL removal: no account reads two tenants by token."""
    user = UserFactory(school=None, is_superuser=True, is_staff=True)
    with pytest.raises(AuthenticationFailed, match='no school'):
        resolve_scope(user, None)


def test_a_forged_claim_for_another_school_does_not_grant_it(school_a, school_b):
    """The signature is real; the claim still loses to user.school_id."""
    from apps.authentication.school_cache import uuid_for_school_pk
    user = AdminUserFactory(school=school_a)
    refresh = RefreshToken.for_user(user)
    refresh['school_uuid'] = uuid_for_school_pk(school_b.pk)

    decoded = jwt.decode(
        str(refresh.access_token), settings.SECRET_KEY, algorithms=['HS256'],
    )
    assert decoded['school_uuid'] == uuid_for_school_pk(school_b.pk)
    with pytest.raises(AuthenticationFailed):
        resolve_scope(user, decoded['school_uuid'])


# ── issuing the claim ────────────────────────────────────────────────────────

def test_login_puts_the_school_on_the_refresh_token(api_client, school_a):
    from apps.authentication.school_cache import uuid_for_school_pk
    user = AdminUserFactory(school=school_a, username='a@test.kz')

    response = api_client.post(
        '/api/v1/auth/login/', {'username': 'a@test.kz', 'password': 'testpass123'},
    )
    assert response.status_code == 200, response.data

    expected = uuid_for_school_pk(school_a.pk)
    for kind in ('refresh', 'access'):
        decoded = jwt.decode(
            response.data['tokens'][kind], settings.SECRET_KEY, algorithms=['HS256'],
        )
        assert decoded['school_uuid'] == expected, kind

    assert response.data['school']['uuid'] == expected
    assert response.data['school']['name'] == school_a.name


def test_the_claim_survives_refresh_rotation(api_client, school_a):
    """ROTATE_REFRESH_TOKENS re-signs the same payload — so it must be there.

    Put on the access token instead, the claim would vanish at the first
    refresh, 30 minutes after login.
    """
    from apps.authentication.school_cache import uuid_for_school_pk
    AdminUserFactory(school=school_a, username='a@test.kz')
    login = api_client.post(
        '/api/v1/auth/login/', {'username': 'a@test.kz', 'password': 'testpass123'},
    )

    refreshed = api_client.post(
        '/api/v1/auth/token/refresh/', {'refresh': login.data['tokens']['refresh']},
    )
    assert refreshed.status_code == 200, refreshed.data

    expected = uuid_for_school_pk(school_a.pk)
    decoded = jwt.decode(
        refreshed.data['access'], settings.SECRET_KEY, algorithms=['HS256'],
    )
    assert decoded['school_uuid'] == expected
