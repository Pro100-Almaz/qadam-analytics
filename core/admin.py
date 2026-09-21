"""The admin site, and the school switcher in its header.

Every admin request acts in exactly one school (`core.middleware`), so the
header has to say which — an admin that silently changes tenant between page
loads is worse than one that shows every school at once. The switcher is the
control for that, and `each_context` is what puts it on every page including
the change forms, which is where being in the wrong tenant actually costs you
something.

Two mechanics worth not rediscovering:

* **The switch is a POST, never a GET.** A GET switcher is CSRF-able and, worse,
  link-shareable: someone pastes you a URL and your tenant flips underneath the
  form you were about to submit.
* **The choice lives in the session, so it is shared across browser tabs.** Open
  school A in one tab and school B in another and the second retargets the
  first. There is no per-tab state in Django's admin to hang this on short of
  putting the school in every URL, so the mitigation is to make the current
  school loud rather than to pretend the problem is not there — hence the
  accent colour and the label, rather than a discreet dropdown tucked into the
  user tools.
"""

import posixpath
from urllib.parse import urlsplit, urlunsplit

from django.contrib.admin import AdminSite, ModelAdmin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from apps.authentication.school_selection import (
    SESSION_KEY,
    is_selectable,
    selectable_schools,
)
from core.admin_mixins import SchoolScopedAdminMixin
from core.tenancy import get_active_school


class QadamAdminSite(AdminSite):
    """Stock AdminSite plus the switcher. Branding is deliberately untouched."""

    def register(self, model_or_iterable, admin_class=None, **options):
        """Scope every ModelAdmin on this site, whether it asked to be or not.

        The manager layer is default-on and fail-closed (§1) because 750 call
        sites cannot be audited one at a time; the admin is the same argument
        with 30 registrations. A `SchoolScopedAdminMixin` a developer has to
        remember is a rule that rots — the one registration that forgets it is
        the one that shows the other tenant's users.

        So it is injected here instead. The synthesized subclass borrows the
        original's identity, because `ModelAdmin` class names surface in system
        check messages and in the `admin/` template lookup paths.

        Inlines need no equivalent: every inline model on this site reaches a
        school through a scoped default manager, so their querysets and pickers
        already narrow. Add one whose FK points at `CustomUser` and it will
        need the mixin explicitly.
        """
        admin_class = admin_class or ModelAdmin
        if not issubclass(admin_class, SchoolScopedAdminMixin):
            admin_class = type(
                admin_class.__name__,
                (SchoolScopedAdminMixin, admin_class),
                {
                    '__module__': admin_class.__module__,
                    '__qualname__': admin_class.__qualname__,
                    '__doc__': admin_class.__doc__,
                },
            )
        return super().register(model_or_iterable, admin_class, **options)

    def get_urls(self):
        # Before super()'s catch-all, which would otherwise swallow the path.
        return [
            path(
                'switch-school/',
                self.admin_view(switch_school),
                name='switch_school',
            ),
        ] + super().get_urls()

    def each_context(self, request):
        context = super().each_context(request)
        active = get_active_school()
        active_id = active if isinstance(active, int) else None
        context.update(
            school_switcher_choices=selectable_schools(request.user),
            school_switcher_active_id=active_id,
            school_switcher_accent=accent_for_school(active_id),
            school_switcher_url=reverse(f'{self.name}:switch_school'),
        )
        return context


#: Distinct, stable, and legible against both admin themes. Cycled by school
#: pk so the two tenants never look alike at a glance — the bar is the only
#: thing on a change form that says which school you are editing, so it has to
#: read as different, not merely say something different.
SCHOOL_ACCENTS = ('#0c7a5b', '#8c4a00', '#5a3fa0', '#1c5f9e', '#9c1f4a')


def accent_for_school(school_pk):
    if not school_pk:
        return 'var(--primary)'
    return SCHOOL_ACCENTS[(school_pk - 1) % len(SCHOOL_ACCENTS)]


@require_POST
def switch_school(request):
    """Point the session at another school and return where you came from.

    Validated against `is_selectable` here *and* on every subsequent read in
    `resolve_admin_school` — this call is where a bad value would enter, the
    read is where a value that went bad after the fact is caught.

    The field is `active_school`, not `school`: the switcher renders on every
    page including add and change forms, most of which have a model field
    called `school`, and two controls of the same name on one page is a trap
    for both the reader and the test.
    """
    if not request.user.is_superuser:
        # 403 rather than `user_passes_test`, which would bounce a logged-in
        # staff member to LOGIN_URL — a route the HTML layer's retirement took
        # away. They are already authenticated; this is a permission answer.
        raise PermissionDenied

    chosen = request.POST.get('active_school')
    if is_selectable(request.user, chosen):
        request.session[SESSION_KEY] = int(chosen)

    admin_index = reverse(f'{request.resolver_match.namespace}:index')
    return HttpResponseRedirect(
        _safe_next(request.POST.get('next'), admin_index) or admin_index
    )


def _safe_next(target, admin_index):
    """`next` if it is a path inside the admin, else None.

    Whitelisted rather than trusted: it arrives as a POST field, so an open
    redirect here would be a phishing primitive on a URL that looks like the
    customer's own admin. Three separate things have to hold —

    * no scheme and no netloc, which rules out `https://evil.example` and the
      protocol-relative `//evil.example`;
    * the path, **normalised**, is under the admin prefix. Without normalising,
      `/admin/../somewhere` passes a plain `startswith` and the browser then
      resolves it to `/somewhere`;
    * the query string is carried over, so switching school from a filtered
      changelist comes back to the same filter.
    """
    if not target:
        return None

    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None

    prefix = admin_index.rstrip('/')
    normalised = posixpath.normpath(parts.path)
    if normalised != prefix and not normalised.startswith(prefix + '/'):
        return None

    # The ORIGINAL path, not the normalised one: normpath strips the trailing
    # slash every admin URL ends with, and handing the browser
    # `/admin/home/subject` would bounce through APPEND_SLASH on every switch.
    # Normalising was only ever the safety check.
    return urlunsplit(('', '', parts.path, parts.query, ''))
