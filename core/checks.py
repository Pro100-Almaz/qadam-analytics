"""`manage.py check` gate for tenant isolation.

The design in core.tenancy leans on one sentence: *a new model fails the build
until someone classifies it*. These checks are that sentence. They run on every
`manage.py check`, so CI refuses a model that is neither scoped nor explicitly
declared shared, and refuses a SCHOOL_PATH that would silently drop rows.

The second check is the general form of the bug that motivated the whole
design. `queryset.filter(offering__school=s)` compiles to an INNER JOIN, so a
row whose `offering` is NULL matches nothing — it vanishes from every queryset,
for every user, in every school, while looking exactly like isolation working.
Nothing is deleted and it is fully recoverable, but it reads as "the feature is
broken" and there is no error to grep for. A model whose path crosses a
nullable link must carry its own non-null `school` column instead.
"""

from django.apps import apps as django_apps
from django.core.checks import Error, Tags, register

#: Apps whose models are tenant data. Everything else (auth.Group, ContentType,
#: Session, admin log, simple_history's own tables) is shared by definition.
TENANT_APPS = frozenset({
    'authentication', 'home', 'lesson',
    'notification', 'achievement', 'student_report',
})

#: Models inside a tenant app that are deliberately NOT scoped, each with the
#: reason. Anything not listed here and not carrying SCHOOL_PATH is an error.
SHARED_MODELS = {
    'authentication.School':
        'The tenant root itself — you cannot scope the thing you scope by.',
    'home.GradeLevel':
        'Grades 1-11 are universal, not per-school; rollover_academic_year does '
        'get_or_create(number=n) against a single shared table.',
}

#: Models whose DEFAULT manager is deliberately unscoped, with the reason.
UNSCOPED_DEFAULT_MANAGER = {
    'authentication.CustomUser':
        'Identity lookups must be global: ModelBackend.authenticate calls '
        '_default_manager.get_by_natural_key() before anyone knows who the user '
        'is, so a fail-closed default manager makes login itself raise. Same for '
        'JWTAuthentication.get_user, PasswordResetForm and createsuperuser. '
        'Isolation is enforced through the five profile models instead; '
        '`CustomUser.in_school` is the scoped manager for listings and pickers.',
}

#: Nullable links that the second check tolerates, each with the reason it is
#: safe. Keep this list at zero entries wherever possible — every entry is a
#: place where a row *could* become visible to no school at all.
NULLABLE_LINK_EXEMPTIONS = {
    'authentication.CustomUser.school':
        'Nullable only so `createsuperuser` works; the DB check constraint '
        '`user_has_school_unless_superuser` bounds NULL to superusers, who '
        'resolve to ALL scope and hold no Student/Teacher/Parent profile. A '
        'profile row belonging to a schoolless superuser would be invisible to '
        'every school — the conservation test is what would surface it.',
}


def _is_historical(model):
    """simple_history's shadow tables. Deferred: the history admin is hidden."""
    return hasattr(model, 'instance_type') or model.__name__.startswith('Historical')


def _tenant_models():
    """Declared models only.

    Auto-created M2M through-tables are deliberately excluded: no application
    code queries them by name, and the cross-tenant risk they carry — stitching
    school A's row to school B's via `.add()`, which never calls save() — is
    handled by the m2m_changed receiver in Phase 6, not by a manager. The four
    that matter are Parent.students, Club.members, Student.subjects and
    ClassGroupCollection.minor_groups.
    """
    for model in django_apps.get_models():
        if model._meta.app_label not in TENANT_APPS or _is_historical(model):
            continue
        yield model


def _walk(model, path):
    """Resolve a SCHOOL_PATH, yielding (owner, field) for each link."""
    current = model
    parts = path.split('__')
    for i, part in enumerate(parts):
        try:
            field = current._meta.get_field(part)
        except Exception:
            raise LookupError(f'{current._meta.label} has no field {part!r}')
        if i < len(parts) - 1:
            if not field.is_relation or field.related_model is None:
                raise LookupError(
                    f'{current._meta.label}.{part} is not a relation, so the '
                    f'path cannot continue past it'
                )
            yield current, field
            current = field.related_model
        else:
            yield current, field


@register(Tags.models)
def check_every_model_is_classified(app_configs=None, **kwargs):
    """Every tenant model is scoped, or explicitly shared."""
    errors = []
    for model in _tenant_models():
        label = model._meta.label
        path = getattr(model, 'SCHOOL_PATH', None)
        shared = label in SHARED_MODELS
        if path and shared:
            errors.append(Error(
                f'{label} declares SCHOOL_PATH but is also in SHARED_MODELS.',
                hint='Pick one. A model is either tenant data or it is not.',
                id='tenancy.E001',
            ))
        elif not path and not shared:
            errors.append(Error(
                f'{label} is in a tenant app but is neither scoped nor shared.',
                hint=(
                    'Add SCHOOL_PATH = "<path to authentication.School>" to the '
                    'model, or add it to core.checks.SHARED_MODELS with the '
                    'reason it is not per-school.'
                ),
                id='tenancy.E002',
            ))
    return errors


@register(Tags.models)
def check_school_paths_resolve(app_configs=None, **kwargs):
    """Every SCHOOL_PATH reaches authentication.School."""
    errors = []
    School = django_apps.get_model('authentication', 'School')
    for model in _tenant_models():
        path = getattr(model, 'SCHOOL_PATH', None)
        if not path:
            continue
        try:
            links = list(_walk(model, path))
        except LookupError as exc:
            errors.append(Error(
                f'{model._meta.label}.SCHOOL_PATH = {path!r} does not resolve: {exc}',
                id='tenancy.E003',
            ))
            continue
        _, last = links[-1]
        if last.related_model is not School:
            errors.append(Error(
                f'{model._meta.label}.SCHOOL_PATH = {path!r} ends at '
                f'{last.related_model and last.related_model._meta.label}, '
                f'not authentication.School.',
                id='tenancy.E004',
            ))
    return errors


@register(Tags.models)
def check_no_nullable_link_in_school_path(app_configs=None, **kwargs):
    """No link in any SCHOOL_PATH is nullable.

    This is the check that exists to catch the SubjectSchedule class of bug
    mechanically, before it reaches a queryset.
    """
    errors = []
    for model in _tenant_models():
        path = getattr(model, 'SCHOOL_PATH', None)
        if not path:
            continue
        try:
            links = list(_walk(model, path))
        except LookupError:
            continue  # already reported by check_school_paths_resolve
        for owner, field in links:
            if not field.null:
                continue
            if f'{owner._meta.label}.{field.name}' in NULLABLE_LINK_EXEMPTIONS:
                continue
            errors.append(Error(
                f'{model._meta.label}.SCHOOL_PATH = {path!r} crosses the '
                f'nullable {owner._meta.label}.{field.name}.',
                hint=(
                    'A filter across a nullable FK becomes an INNER JOIN, so '
                    'every row with NULL there becomes invisible to EVERY '
                    'school while looking like isolation is working. Give this '
                    'model its own non-null `school` column and set '
                    'SCHOOL_PATH = "school", or route the path through a '
                    'non-null FK.'
                ),
                id='tenancy.E005',
            ))
    return errors


@register(Tags.models)
def check_scoped_models_have_a_scoped_manager(app_configs=None, **kwargs):
    """SCHOOL_PATH without a scoped default manager is decorative.

    The path is only ever read by `apply_school_scope`, which runs inside a
    manager's `get_queryset`. A model that declares the path but keeps a plain
    `models.Manager()` reads as isolated and is not — it is the same silent
    failure as a wrong path, with nothing in the code to show for it.
    """
    from core.tenancy import SchoolScopedManagerMixin

    errors = []
    for model in _tenant_models():
        if not getattr(model, 'SCHOOL_PATH', None):
            continue
        manager = model._meta.default_manager
        if isinstance(manager, SchoolScopedManagerMixin):
            continue
        if model._meta.label in UNSCOPED_DEFAULT_MANAGER:
            continue
        errors.append(Error(
            f'{model._meta.label} declares SCHOOL_PATH but its default manager '
            f'({type(manager).__name__}) does not apply the scope.',
            hint=(
                'Add `objects = SchoolScopedManager()` to the model, or compose '
                'SchoolScopedManagerMixin into its existing manager (mixin '
                'first, so the scope filter is applied on top).'
            ),
            id='tenancy.E006',
        ))
    return errors


@register()
def check_school_scope_mode_is_valid(app_configs=None, **kwargs):
    """`SCHOOL_SCOPE_MODE` names one of the three ramp settings.

    `get_scope_mode()` raises on an unknown value, but it is called from inside
    `get_queryset()` — so a typo in the env var is not a startup failure, it is
    a 500 on every request that touches a scoped model, discovered in
    production. Checking it here turns that into a failed deploy. The runtime
    raise stays as the backstop for a value set after startup (a test using
    `override_settings`, say).
    """
    from django.conf import settings

    from core.tenancy import VALID_MODES

    mode = getattr(settings, 'SCHOOL_SCOPE_MODE', 'enforce')
    if mode in VALID_MODES:
        return []
    return [Error(
        f'SCHOOL_SCOPE_MODE={mode!r} is not one of {VALID_MODES}.',
        hint=(
            'This is read per-queryset, not at startup, so an unrecognised '
            'value would 500 every request against a scoped model rather than '
            'failing the boot. Set the env var to "off", "warn" or "enforce".'
        ),
        id='tenancy.E007',
    )]
