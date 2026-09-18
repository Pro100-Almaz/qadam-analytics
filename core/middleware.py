"""Per-request school scope for the session-authenticated half of the app.

Ordering is the whole subtlety here. `AuthenticationMiddleware` sets
`request.user` from the **session only**, and DRF authenticates much later, in
`APIView.initial()`. So for an API request carrying a JWT this middleware sees
`AnonymousUser` and sets `UNSET`; the DRF authentication class then narrows to
the real scope. For `/admin/` there is no token at all, and this is the only
thing that runs.

That split is what implements the §4 decision rather than merely coexisting
with it:

    /admin/, superuser, session auth   ->  ALL          (cross-school lives here)
    everything else                    ->  the user's own school
    anonymous                          ->  UNSET        (fail closed)

`ALL` is deliberately tied to the admin path rather than to `is_superuser`
alone. A superuser hitting the DRF API — with a token, or with an admin session
cookie still in the jar — gets their own school like anyone else, so a mistyped
cross-school id 404s instead of silently landing in another tenant. Cross-school
work happens on the one surface where the actor can see what they are touching.
"""

from django.urls import reverse

from core.tenancy import ALL, UNSET, reset_active_school, set_active_school


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
            # The phase-7 switcher writes this; until then a superuser in the
            # admin simply sees every school.
            chosen = (request.session or {}).get('active_school_id')
            return chosen if chosen else ALL

        if user.school_id is None:
            # Only reachable for a superuser created by `createsuperuser`, who
            # has no school to scope to — so the cross-school sentinel is the
            # only workable answer, and `resolve_scope` in the DRF auth class
            # says the same. This is the one exception to "superusers get their
            # own school outside /admin/": give such an account a school and
            # the exception stops applying to it.
            #
            # Anyone else with no school fails closed. The phase-1 check
            # constraint `user_has_school_unless_superuser` means there is no
            # such user, but the branch does not depend on that holding.
            return ALL if user.is_superuser else UNSET

        return user.school_id

    def __call__(self, request):
        token = set_active_school(self.resolve_scope_for_request(request))
        try:
            return self.get_response(request)
        finally:
            reset_active_school(token)
