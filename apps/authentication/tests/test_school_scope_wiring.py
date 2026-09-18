"""How a request gets its school: the middleware and the DRF auth class.

These two are the whole of phase 3's isolation wiring, and between them they
implement the §4 decision that cross-school access lives in `/admin/` and
nowhere else. That decision is a security boundary, so it is pinned from both
sides — what each surface grants, and what it refuses.
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
from core.tenancy import ALL, UNSET, get_active_school

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


def test_a_superuser_in_the_admin_sees_every_school(school_a):
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert _scope_for(user, path='/admin/home/subject/') is ALL


def test_a_superuser_outside_the_admin_gets_only_their_own_school(school_a):
    """The §4 decision, and the reason it is path-based rather than role-based.

    A superuser holding an admin session cookie and hitting the API still gets
    their own school — so a mistyped cross-school id 404s instead of silently
    landing in another tenant. Cross-school work happens where it is visible.
    """
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert _scope_for(user, path='/api/v1/students/') == school_a.pk


def test_the_admin_switcher_hook_narrows_a_superuser(school_a, school_b):
    """Phase 7 writes this session key; the middleware already honours it."""
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    scope = _scope_for(
        user, path='/admin/', session={'active_school_id': school_b.pk},
    )
    assert scope == school_b.pk


def test_a_schoolless_superuser_outside_the_admin_still_gets_all():
    """`createsuperuser` leaves no school; there is nothing to scope to."""
    user = UserFactory(school=None, is_superuser=True, is_staff=True)
    assert _scope_for(user, path='/api/v1/students/') is ALL


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
    """ALL is reached through /admin/ only — never through a token."""
    user = UserFactory(school=school_a, is_superuser=True, is_staff=True)
    assert resolve_scope(user, None) == school_a.pk


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
