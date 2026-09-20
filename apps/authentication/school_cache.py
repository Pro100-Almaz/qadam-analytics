"""uuid <-> pk translation for the tenant root, with a process-local cache.

The design carries the active school two different ways on purpose:

* **On the wire it is the `uuid`.** Never the sequential pk, which would leak
  the tenant count and their creation order to anyone holding a token.
* **In the scope it is the pk.** `core.tenancy._as_scope` stores a plain
  integer, because the value outlives any single query and an int cannot drag a
  stale row (or a DB connection) around with it.

So the JWT path needs both directions: uuid -> pk to enter a scope from a
token claim, and pk -> uuid to check that claim against `user.school_id`.

Why this lives in `apps.authentication` rather than `core.tenancy`
------------------------------------------------------------------
`core.tenancy` is imported at module level by `core/models.py` and by every
app's `models.py` — that is how `SchoolScopedManager` reaches the models. It
therefore cannot import `apps.authentication.models` at module level without a
cycle. Here there is no cycle, and the invalidation hook sits next to the model
it fires on.

Why a cache
-----------
The claim check is only "free" if turning `user.school_id` into a uuid is free.
Without this it is an extra SELECT on School for every authenticated request,
which quietly undoes that argument.

What the cache can and cannot get wrong
---------------------------------------
`uuid` is `editable=False` and a pk never changes, so **a cached entry can
never become wrong** — the mapping is immutable for the life of a row. It can
only be *absent*, for a school created after this process warmed up. That is
why the miss path, not invalidation, is what makes this correct.

Two consequences worth stating, because both are easy to get wrong:

* **Misses are never cached.** `school_pk_for_uuid` is driven by a value from a
  token claim. Caching misses would let a client grow this dict without bound
  by sending random uuids.
* **The receivers below are not a distributed invalidation.** A module-level
  dict is per-process: under gunicorn, a `School.save()` in worker 3 clears
  worker 3 and nothing else. Other workers are covered by the miss path, not by
  the signal. The receivers earn their place in the single-process cases —
  runserver, tests, management commands — where a stale entry would survive a
  rename or a delete and be genuinely confusing.

Lookups go through `School.objects` (unscoped), never `School.visible`. A user
whose school has been deactivated must still *resolve* to that school; refusing
them is an authorization decision for the caller, not something to express by
making the tenant invisible and silently falling through to UNSET.
"""

import uuid as uuid_module

from django.db.models.signals import post_delete, post_save

_pk_by_uuid: dict[str, int] = {}
_uuid_by_pk: dict[int, str] = {}


def _normalise(value):
    """Canonical string form, or None if it is not a uuid at all.

    The claim is signed, so its origin is trustworthy, but it can still be
    malformed or name a school that no longer exists. Returning None lets the
    caller answer with AuthenticationFailed rather than a 500.
    """
    if value is None:
        return None
    if isinstance(value, uuid_module.UUID):
        return str(value)
    try:
        return str(uuid_module.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def school_pk_for_uuid(value):
    """The pk of the School with this uuid, or None."""
    key = _normalise(value)
    if key is None:
        return None
    cached = _pk_by_uuid.get(key)
    if cached is not None:
        return cached

    from apps.authentication.models import School
    pk = School.objects.filter(uuid=key).values_list('pk', flat=True).first()
    if pk is None:
        return None            # deliberately not cached — see the module docstring
    _remember(pk, key)
    return pk


def uuid_for_school_pk(pk):
    """The uuid of the School with this pk, as a string, or None."""
    if pk is None:
        return None
    cached = _uuid_by_pk.get(pk)
    if cached is not None:
        return cached

    from apps.authentication.models import School
    value = School.objects.filter(pk=pk).values_list('uuid', flat=True).first()
    if value is None:
        return None
    key = _normalise(value)
    _remember(pk, key)
    return key


def _remember(pk, key):
    _pk_by_uuid[key] = pk
    _uuid_by_pk[pk] = key


def clear_school_cache():
    """Drop everything this process has memoised.

    Tests must call this between cases: the DB rolls back but the dict does
    not, and rolled-back pks are reissued — so a stale entry would map a reused
    pk to the previous test's uuid. conftest does it autouse.
    """
    _pk_by_uuid.clear()
    _uuid_by_pk.clear()


def _invalidate(sender, **kwargs):
    clear_school_cache()


def _register_invalidation():
    """Connect the receivers. Called from AuthenticationConfig.ready().

    Registered from ready() rather than on import so it happens in every
    process, including management commands that never load the URLconf and so
    never import whatever ends up calling the lookups.

    weak=False, and `_invalidate` lives at module level rather than in here.
    Both matter: a receiver defined inside this function has no reference left
    once it returns, and Signal.connect stores only a weakref by default, so
    the connection dies the moment the function object is collected. Under
    DEBUG the connection happened to survive — Django's `func_accepts_kwargs`
    check runs only then, and its lru_cache was what held the reference — so
    this looked correct everywhere except the configuration production runs:
    with DEBUG=False, renaming or deleting a School left every worker serving
    the stale uuid->pk map for the life of the process.
    """
    from apps.authentication.models import School

    post_save.connect(
        _invalidate, sender=School, weak=False,
        dispatch_uid='school_cache_invalidate_save',
    )
    post_delete.connect(
        _invalidate, sender=School, weak=False,
        dispatch_uid='school_cache_invalidate_delete',
    )
