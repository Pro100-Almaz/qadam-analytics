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
school like anyone else; `ALL` is reached only through `/admin/` on session
auth (see core.middleware). A mistyped cross-school id therefore 404s rather
than silently landing in another tenant.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.authentication.school_cache import uuid_for_school_pk
from core.tenancy import ALL, set_active_school


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
        # Only a `createsuperuser` account reaches this. There is no school to
        # scope to, so the cross-school sentinel is the only workable answer.
        if user.is_superuser:
            return ALL
        raise AuthenticationFailed('User has no school.')

    if claim_uuid and str(claim_uuid) != uuid_for_school_pk(user.school_id):
        raise AuthenticationFailed('Token school does not match user.')

    return user.school_id
