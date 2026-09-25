"""Which school a superuser is *looking at* in /admin/, and which they may pick.

`/admin/` used to resolve superusers to the `ALL` sentinel, so every changelist
mixed both tenants. That was never a permission — a superuser can reach every
school either way — but it made three things wrong at once:

* Every list answered "which school is this row from?" only if you added the
  column and read it.
* `SchoolScopedAdminMixin.save_model` had no school to stamp on a new row, so
  it fell back to the *acting user's* school. Browsing school B and clicking
  Add wrote a school A row, silently.
* `AcademicYear.objects.filter(is_active=True).first()` and friends — seven
  call sites in the admin — became ambiguous the moment a tenant model had
  more than one candidate row.

So the admin now always names exactly one school, chosen here. `ALL` is gone
from the request path entirely; `core.tenancy.all_schools()` remains for
migrations, scripts and the shell, where cross-school work is explicit and
auditable.

Nothing here is an authorization decision. A superuser may select any school —
that is what `is_superuser` means — and a non-superuser never reaches this
module, because the middleware scopes them to `user.school_id` before asking.
"""

#: Where the chosen school's pk lives between requests.
SESSION_KEY = 'active_school_id'


def selectable_schools(user):
    """The schools `user` may switch between. Empty for anyone but a superuser.

    Deactivated schools are included on purpose: `School.is_active` marks a
    tenant that is no longer *served*, not one that is off limits to the person
    who has to go in and finish winding it down.
    """
    from apps.authentication.models import School

    if not (user and user.is_authenticated and user.is_superuser):
        return School.objects.none()
    return School.objects.order_by('name')


def is_selectable(user, school_pk):
    """Is `school_pk` a school this user may switch to right now?

    Called on every admin request, not only on the POST that sets it: a session
    can outlive the school it names (deleted, or the account demoted), and a
    stale value must not resolve into a scope. Validating on read is what makes
    the session safe to trust.
    """
    if school_pk is None:
        return False
    try:
        school_pk = int(school_pk)
    except (TypeError, ValueError):
        return False
    return selectable_schools(user).filter(pk=school_pk).exists()


def default_school_pk(user):
    """The school a superuser lands on before they touch the switcher.

    Their own school when they have one — "the school they work at" is the
    right default and the overwhelmingly common case. A `createsuperuser`
    account has none (the `user_has_school_unless_superuser` constraint allows
    exactly that), and failing closed there would lock the only account able to
    fix it out of the admin, so it falls back to the first school by name.
    Returns None only when no school exists at all.
    """
    from apps.authentication.models import School

    if getattr(user, 'school_id', None) is not None:
        return user.school_id
    return School.objects.order_by('name').values_list('pk', flat=True).first()


def resolve_admin_school(request, user):
    """The one school this admin request acts in, or None if none exists yet."""
    session = getattr(request, 'session', None)
    chosen = session.get(SESSION_KEY) if session is not None else None
    if is_selectable(user, chosen):
        return int(chosen)
    return default_school_pk(user)
