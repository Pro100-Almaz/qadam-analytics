"""Per-request school scope for the session-authenticated half of the app.

Ordering is the whole subtlety here. `AuthenticationMiddleware` sets
`request.user` from the **session only**, and DRF authenticates much later, in
`APIView.initial()`. So for an API request carrying a JWT this middleware sees
`AnonymousUser` and sets `UNSET`; the DRF authentication class then narrows to
the real scope. For `/admin/` there is no token at all, and this is the only
thing that runs.

That split is what implements the §4 decision rather than merely coexisting
with it:

    /admin/, superuser, session auth   ->  the school the switcher names
    everything else                    ->  the user's own school
    anonymous                          ->  UNSET        (fail closed)

**No request ever resolves to `ALL`.** A superuser in the admin sees exactly
one school at a time — their own by default, any other by picking it from the
header switcher, which writes `session['active_school_id']`. That is a view
selector and not a permission (a superuser may still pick any school), but it
means every admin page has an unambiguous answer to "which tenant am I in",
which is what `save_model` stamping and the active-academic-year lookups need.
`core.tenancy.all_schools()` still exists for migrations, scripts and the
shell — cross-school work belongs where it is written down, not where it is
the silent default.

A superuser hitting the DRF API — with a token, or with an admin session cookie
still in the jar — gets their own school like anyone else, so a mistyped
cross-school id 404s instead of silently landing in another tenant.
"""

from django.urls import reverse

from apps.authentication.school_selection import resolve_admin_school
from core.tenancy import UNSET, reset_active_school, set_active_school


class SchoolScopeMiddleware:
    """Owns the per-request contextvar token.

    Under WSGI a gunicorn worker thread's context is reused between requests, so
    the token MUST be reset here. The DRF auth class `set()`s a narrower scope
    inside this window; `reset(token)` restores the value as of token creation
    regardless of how many `set()` calls happened in between, so one `finally`
    cleans up both layers.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._admin_prefix = None

    @property
    def admin_prefix(self):
        # Resolved lazily and cached: the URLconf is not loaded when middleware
        # is constructed. Derived from the URLconf rather than hardcoded, so
        # moving the admin does not silently move the cross-school boundary.
        if self._admin_prefix is None:
            try:
                self._admin_prefix = reverse('admin:index')
            except Exception:
                self._admin_prefix = '/admin/'
        return self._admin_prefix

    def resolve_scope_for_request(self, request):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return UNSET

        if user.is_superuser and request.path.startswith(self.admin_prefix):
            # Exactly one school, always — the switcher's choice if the session
            # names one this user may still select, else their own, else the
            # first school that exists. See apps.authentication.school_selection
            # for why each fallback is where it is.
            chosen = resolve_admin_school(request, user)
            return chosen if chosen is not None else UNSET

        if user.school_id is None:
            # A `createsuperuser` account with no school yet. It has no tenant
            # to act in outside the admin, and there is no sentinel to widen to
            # any more, so it fails closed here like anyone else — the admin
            # (above) is where it goes to give itself a school. Everyone else
            # with no school is barred by the `user_has_school_unless_superuser`
            # check constraint, but this branch does not rely on that holding.
            return UNSET

        return user.school_id

    def __call__(self, request):
        token = set_active_school(self.resolve_scope_for_request(request))
        try:
            return self.get_response(request)
        finally:
            reset_active_school(token)
