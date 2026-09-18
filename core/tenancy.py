"""School (tenant) scoping — isolation that is default-on and fails closed.

The platform has ~750 `.objects.` call sites and 133 DRF view classes, only 29
of which define `get_queryset`. Filtering per view is not reachable, so the
filter lives in the **default manager** instead: `Model.objects` returns only
the active school's rows and code must opt out explicitly. Django routes
reverse FKs, M2M, `ModelChoiceField` and `ModelAdmin.get_queryset` through the
default manager, so all of those narrow with no edits; forward FKs and cascade
deletes go through `_base_manager` and stay unscoped, which is what they need.

The active school is carried in a `contextvars.ContextVar`, not a
`threading.local`: each thread starts with a fresh, empty context, it
propagates through `asgiref.sync`, and a Celery prefork worker starts empty ->
UNSET -> fails closed, which is the behaviour we want.

`SCHOOL_SCOPE_MODE` is the rollout ramp, and the rollback:

    'off'      the filter never applies. Phase 2-3 land inert.
    'warn'     the filter applies when a scope is active; querying with no
               scope logs an ERROR with a stack trace and returns unfiltered.
    'enforce'  querying with no scope raises SchoolScopeError.

Flipping ~750 call sites to fail-closed in one deploy is reckless, so the ramp
is off -> warn -> (drain the error log) -> enforce, and 'warn' stays deployable
as a one-env-var rollback for a month past the flip.
"""

import contextvars
import logging
from contextlib import contextmanager

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

VALID_MODES = ('off', 'warn', 'enforce')


class SchoolScopeError(RuntimeError):
    """A school-scoped model was queried with no active scope."""


class SchoolDerivationError(RuntimeError):
    """A row with its own `school` column could not work out which school.

    Raised by SchoolDerivedMixin.save() in place of the NOT NULL IntegrityError
    that would follow, because the constraint violation names the column and
    nothing else — not which source came back empty, nor that passing `school`
    explicitly is the fix.
    """


class _Sentinel:
    __slots__ = ('_name',)

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return self._name


#: Nobody entered a scope. Fail closed — this is the whole point of the design.
UNSET = _Sentinel('UNSET')
#: Deliberate cross-school access: superusers, migrations, management scripts.
ALL = _Sentinel('ALL')

_active_school = contextvars.ContextVar('qadam_active_school', default=UNSET)


def get_scope_mode():
    """Read the ramp setting, defaulting to the safe end if it is absent."""
    mode = getattr(settings, 'SCHOOL_SCOPE_MODE', 'enforce')
    if mode not in VALID_MODES:
        raise ValueError(
            f'SCHOOL_SCOPE_MODE={mode!r} is not one of {VALID_MODES}.'
        )
    return mode


def _as_scope(school):
    """Normalise a School, a pk, or a sentinel into what the ContextVar holds.

    A pk rather than an instance: the value outlives any single query, and a
    plain int cannot drag a stale row (or a DB connection) around with it.
    """
    if school is UNSET or school is ALL:
        return school
    if school is None:
        raise ValueError(
            'school_scope(None) is not meaningful. Use all_schools() for '
            'deliberate cross-school access, or pass a School.'
        )
    return getattr(school, 'pk', school)


def get_active_school():
    """The active scope: a School pk, or the UNSET / ALL sentinel."""
    return _active_school.get()


def set_active_school(school):
    """Set the scope and return the reset token. Prefer `school_scope()`.

    Used by the middleware and the DRF authentication class, which set a scope
    that has to outlive the call rather than a `with` block.
    """
    return _active_school.set(_as_scope(school))


def reset_active_school(token):
    _active_school.reset(token)


@contextmanager
def school_scope(school):
    """Run a block inside one school. Accepts a School instance or a pk."""
    token = _active_school.set(_as_scope(school))
    try:
        yield
    finally:
        _active_school.reset(token)


@contextmanager
def all_schools():
    """Deliberate cross-school access. Grep for this to audit every use."""
    token = _active_school.set(ALL)
    try:
        yield
    finally:
        _active_school.reset(token)


@contextmanager
def no_school_scope():
    """Force the UNSET state. For tests that assert the fail-closed behaviour."""
    token = _active_school.set(UNSET)
    try:
        yield
    finally:
        _active_school.reset(token)


def apply_school_scope(queryset, model):
    """Narrow `queryset` to the active school. The single chokepoint.

    Models with no `SCHOOL_PATH` are shared (GradeLevel, auth.Group, …) and are
    returned untouched; `core.checks` is what guarantees that is deliberate
    rather than forgotten.
    """
    if get_scope_mode() == 'off':
        return queryset

    path = getattr(model, 'SCHOOL_PATH', None)
    if path is None:
        return queryset

    scope = _active_school.get()
    if scope is ALL:
        return queryset

    if scope is UNSET:
        msg = (
            f'{model._meta.label} queried outside a school scope. Wrap the '
            f'caller in school_scope(...) — or all_schools() if it really is '
            f'cross-school.'
        )
        if get_scope_mode() == 'enforce':
            raise SchoolScopeError(msg)
        logger.error(msg, stack_info=True)
        return queryset

    return queryset.filter(**{path: scope})


class SchoolScopedManagerMixin:
    """Mix in FIRST, so the scope filter composes on top of any other filter.

    `use_in_migrations` stays False: historical models in migrations have no
    SCHOOL_PATH and must see every row.
    """

    use_in_migrations = False

    def get_queryset(self):
        return apply_school_scope(super().get_queryset(), self.model)


class SchoolScopedManager(SchoolScopedManagerMixin, models.Manager):
    """The plain scoped manager, for models with no other manager behaviour."""
