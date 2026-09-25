"""JWT authentication that also enters the request's school scope.

The school travels as a signed claim (`school_uuid`) so the frontend has
something to store and display. The server treats it as a **tripwire, never as
the grant**:

* A claim inside the signed JWT is trustworthy — SimpleJWT verifies the HMAC
  before anything here can read it, so it is exactly as tamper-proof as the
  `user_id` claim already used to authenticate.
* A value the client sends *separately* — an `X-School-Id` header, a query
  param, a body field — is attacker-controlled and is never read.

Even so, the grant is `user.school_id`, not the claim. `JWTAuthentication.get_user()`
has already loaded the user row to authenticate at all, so checking the claim
against it costs no extra query — and it removes the staleness window entirely:
move a user between schools or offboard them and a token minted beforehand
would otherwise assert the old school for up to REFRESH_TOKEN_LIFETIME (7 days).

Superusers are **not** special here. Over the API they are scoped to their own
school like anyone else, so a mistyped cross-school id 404s rather than
silently landing in another tenant. There is no cross-school sentinel on the
request path at all any more — in `/admin/` a superuser picks one school from
the header switcher (see core.middleware), and everywhere else the only
cross-school access is an explicit `all_schools()` in code.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.authentication.school_cache import uuid_for_school_pk
from core.tenancy import set_active_school


class SchoolScopedJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)   # verifies the signature first
        if result is None:
            return None
        user, token = result                     # get_user() already loaded the row
        set_active_school(resolve_scope(user, token.get('school_uuid')))
        return user, token


def resolve_scope(user, claim_uuid):
    """The user's own school is the grant; the claim is only a consistency check."""
    from rest_framework_simplejwt.exceptions import AuthenticationFailed

    if user.school_id is None:
        # Only a `createsuperuser` account reaches this — every other user is
        # held to a school by the `user_has_school_unless_superuser` check
        # constraint. It used to resolve to the cross-school sentinel, which
        # made a schoolless superuser the one account that could read both
        # tenants over the API. It fails closed instead: such an account signs
        # into /admin/, where it lands on a concrete school, and gives itself
        # one. Nothing else in the system needs it to be able to call the API.
        raise AuthenticationFailed('User has no school.')

    if claim_uuid and str(claim_uuid) != uuid_for_school_pk(user.school_id):
        raise AuthenticationFailed('Token school does not match user.')

    return user.school_id
