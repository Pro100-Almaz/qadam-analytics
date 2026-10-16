from django.contrib.auth.models import UserManager
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from core.tenancy import (
    CrossSchoolWriteError, SchoolDerivationError,
    SchoolScopedManagerMixin, apply_school_scope,
)


class SoftDeleteQuerySet(models.QuerySet):
    """Every manager of a soft-deletable model is built from this (spec 0013).

    `delete()` is the soft one, so a queryset delete anywhere in the code —
    a view, a reverse relation, the admin's bulk action — is recoverable.
    `_base_manager` is NOT built from it: Django's own cascade (the purge)
    goes through `_base_manager`, and that is the one path that must really
    remove rows.
    """

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def delete(self, user=None):
        from core.soft_delete import soft_delete
        return soft_delete(self, user=user)
    delete.alters_data = True
    delete.queryset_only = True

    def hard_delete(self):
        return super().delete()
    hard_delete.alters_data = True
    hard_delete.queryset_only = True

    def restore(self):
        """Restore the batch of every row here. One call per batch, not per row."""
        from core.soft_delete import restore
        seen = set()
        for obj in self.filter(is_deleted=True):
            key = obj.deletion_batch or (type(obj), obj.pk)
            if key not in seen:
                seen.add(key)
                restore(obj)
    restore.alters_data = True
    restore.queryset_only = True


_SoftDeleteQuerySetManager = models.Manager.from_queryset(SoftDeleteQuerySet)


class AllRowsManager(_SoftDeleteQuerySetManager):
    """Deleted rows included, no school scope. `SoftDeleteMixin.unscoped`."""


class ScopedAllRowsManager(SchoolScopedManagerMixin, _SoftDeleteQuerySetManager):
    """Deleted rows included, school-scoped. `SoftDeleteMixin.all_objects`."""


class SoftDeleteManager(_SoftDeleteQuerySetManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def _unfiltered(self):
        """Every row, soft-deleted included.

        A hook rather than a direct `super().get_queryset()` in each caller:
        those bypass any `get_queryset` override, so the school filter would be
        skipped by exactly the two methods below. ScopedSoftDeleteManager
        overrides this one method to close that.
        """
        return super().get_queryset()

    def all_with_deleted(self):
        return self._unfiltered()

    def deleted_only(self):
        return self._unfiltered().filter(is_deleted=True)


class ScopedSoftDeleteManager(SchoolScopedManagerMixin, SoftDeleteManager):
    """Soft-delete filtering and school scoping, composed."""

    def _unfiltered(self):
        return apply_school_scope(super()._unfiltered(), self.model)


class SoftDeleteUserManager(UserManager.from_queryset(SoftDeleteQuerySet)):
    """`CustomUser.objects`: live users only, and deliberately NOT school-scoped.

    Unscoped for the reason in `core.checks.UNSCOPED_DEFAULT_MANAGER`. Live-only
    because `ModelBackend` (`get_by_natural_key`) and SimpleJWT (`get_user`)
    both look users up through it, so a soft-deleted user is simply not found
    and can neither log in nor use a token minted before the delete (AC-6).
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


def live_unique_constraint(*, fields, name, condition=None):
    """A UniqueConstraint that only live rows count towards (spec 0013, G-4).

    A soft-deleted row keeps its values, so a plain unique rule would let it
    block a new row with the same value forever. `is_deleted=False` is ANDed
    into any condition the rule already had; `core.soft_delete` strips it
    back off to find the live row that blocks a restore.
    """
    live = models.Q(is_deleted=False)
    return models.UniqueConstraint(
        fields=fields, name=name,
        condition=live & condition if condition is not None else live,
    )


class SoftDeleteMixin(models.Model):
    """Rows are hidden, not removed, and come back as the batch they left in.

    `delete()` collects the same tree a hard delete would (`CASCADE` edges
    only) and stamps all of it with one `deletion_batch`; `restore()` brings
    that batch back. The walker and the guards live in `core.soft_delete`.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        'authentication.CustomUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    #: Shared by every row deleted in one action. NULL on live rows, and on
    #: rows deleted before spec 0013, which restore one at a time.
    deletion_batch = models.UUIDField(
        null=True, blank=True, db_index=True, editable=False,
    )

    # `objects` first: Django takes the first declared manager as the default,
    # and the default manager is what reverse FKs, M2M and the admin go through.
    objects = ScopedSoftDeleteManager()
    #: Soft-deleted rows included, still school-scoped.
    all_objects = ScopedAllRowsManager()
    #: Neither filter. Last resort — one word, and greppable.
    unscoped = AllRowsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, *, user=None, extras=True):
        """Soft delete. `hard_delete()` is the real one, used only by purge."""
        return self.soft_delete(user=user, extras=extras)

    def soft_delete(self, user=None, *, extras=True):
        from core.soft_delete import soft_delete
        return soft_delete([self], user=user, extras=extras)

    def hard_delete(self, using=None, keep_parents=False):
        return models.Model.delete(self, using=using, keep_parents=keep_parents)

    def restore(self):
        from core.soft_delete import restore
        restore(self)

    @classmethod
    def soft_delete_extra(cls, pks):
        """Rows no FK links to that must leave with these (model, pks) pairs.

        Yields `(model, iterable of pks)`. The walker only ever adds live rows.
        """
        return ()


_UNCACHED = object()


def school_id_of(obj):
    """The school a related object belongs to, or None.

    Two ways an object reaches a school, and both have to work here: it carries
    its own `school` column, or it declares a `SCHOOL_PATH` to one. Only
    checking for `school_id` was the bug behind an Attachment on a Club — at the
    time Club was scoped by `academic_year__school` and had no column of its
    own, so the attribute lookup came back None and the derivation fell through.
    Club has since gained a column (§1a), but Achievement, Homework and every
    other attachment target still reach their school by path.

    Cost matters here: since §7 this runs on every save of a join model, and a
    grading POST saves many. So it resolves in the cheapest way that works —
    the cached relation chain if the caller already has the objects in hand,
    otherwise **one** query with the whole path as a join, never one query per
    link.

    That query goes through `_base_manager`, unscoped by design. That is what
    we want: this is working out *which* tenant owns a row, so it must not be
    filtered by the tenant already active.
    """
    if obj is None:
        return None
    school_id = getattr(obj, 'school_id', None)
    if school_id:
        return school_id
    path = getattr(obj, 'SCHOOL_PATH', None)
    if not path:
        return None
    parts = path.split('__')
    if parts[-1] != 'school':
        return None

    current = obj
    for part in parts[:-1]:
        try:
            field = current._meta.get_field(part)
        except Exception:
            return None
        if not field.is_relation or not hasattr(field, 'get_cached_value'):
            return None
        try:
            current = field.get_cached_value(current)
        except KeyError:
            current = _UNCACHED
            break
        if current is None:
            return None
    if current is not _UNCACHED:
        return getattr(current, 'school_id', None)

    if obj.pk is None:
        return None
    return (
        type(obj)._base_manager
        .filter(pk=obj.pk)
        .values_list(path, flat=True)
        .first()
    )


def _resolve_path(obj, path):
    """Walk a `__`-separated attribute path, stopping at the first None."""
    for part in path.split('__'):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def school_id_through(instance, path):
    """The school reached from `instance` along `path`, in as few queries as possible.

    The common case — `path` is one plain FK — is resolved without loading the
    related object at all when it is not already in memory: one query against
    the related model, its own SCHOOL_PATH as the select. Loading the object
    instead would cost that query plus one per link of its path.
    """
    if '__' not in path:
        try:
            field = instance._meta.get_field(path)
        except FieldDoesNotExist:
            field = None
        if field is not None and field.is_relation and field.concrete:
            try:
                return school_id_of(field.get_cached_value(instance))
            except KeyError:
                pass
            related_id = getattr(instance, field.attname, None)
            if related_id is None:
                return None
            related_model = field.related_model
            related_path = getattr(related_model, 'SCHOOL_PATH', None)
            if not related_path:
                return None
            return (
                related_model._base_manager
                .filter(pk=related_id)
                .values_list(related_path, flat=True)
                .first()
            )
    return school_id_of(_resolve_path(instance, path))


class SchoolConsistentModel(models.Model):
    """Refuses to save a row whose declared FKs point at different schools.

    §7 layer 1, and the second half of *derive when you can, validate when you
    must*: `SchoolDerivedMixin` fills a denormalised column from a parent, this
    checks that the parents agree with each other and with the column.

    In `save()`, not `clean()`. DRF never calls `full_clean()`, and neither
    does `Model.objects.create()` — a validator on `clean()` would be absent
    from every path this repo actually writes through.

    `SCHOOL_CONSISTENT_FIELDS` names the *domain* FKs whose schools must match:
    the offering's subject and class group, the enrollment's student and class
    group. **Not the actor FKs** — `deleted_by`, `added_by`, `generated_by`,
    `uploaded_by`, `frozen_by`. A superuser's own `school` is data about where
    they work, and since §9a they legitimately act inside any one school from
    the admin switcher, so requiring the actor to match the row would break
    exactly the cross-school administration the switcher exists to allow.

    Fields resolving to no school are skipped rather than failing: a
    school-wide `SubjectSchedule` has neither offering nor class group, and a
    half-populated row is valid. Only a *disagreement* is an error.
    """

    #: Tuple of lookup paths (usually plain FK names) that must agree.
    SCHOOL_CONSISTENT_FIELDS: tuple = ()

    class Meta:
        abstract = True

    def _school_ids_of_consistent_fields(self):
        """{field path: school pk} for every declared field that reaches one."""
        found = {}
        for path in self.SCHOOL_CONSISTENT_FIELDS:
            school_id = school_id_through(self, path)
            if school_id:
                found[path] = school_id
        return found

    def validate_school_consistency(self):
        """Raise on a cross-tenant row; stamp `school` when it can be inferred.

        Returns nothing and mutates at most `self.school_id`, so it is safe to
        call more than once.
        """
        found = self._school_ids_of_consistent_fields()
        distinct = set(found.values())
        if len(distinct) > 1:
            raise CrossSchoolWriteError(
                f'{type(self).__name__} would reference more than one school: '
                + ', '.join(f'{path}=school #{sid}' for path, sid in sorted(found.items()))
                + '. A row belongs to exactly one tenant; nothing was saved.'
            )
        if not self._meta_has_school_column():
            return
        own = self.school_id
        if own is None:
            if distinct:
                self.school_id = distinct.pop()
            return
        if distinct and own not in distinct:
            raise CrossSchoolWriteError(
                f'{type(self).__name__}.school is school #{own} but '
                + ', '.join(f'{path}=school #{sid}' for path, sid in sorted(found.items()))
                + '. The column contradicts the row it hangs off; nothing was saved.'
            )

    @classmethod
    def _meta_has_school_column(cls):
        # `fields`, not `local_fields`: a proxy model (MinorClassGroup) has no
        # local fields at all and would otherwise read as column-less.
        return any(f.name == 'school' for f in cls._meta.fields)

    def _fill_missing_school(self):
        """Hook: last chance to set `school` before the write.

        No-op here — validation has already stamped the column from whichever
        declared field reached a school. `SchoolDerivedMixin` overrides it for
        the models whose sources are alternatives rather than peers.
        """

    def save(self, *args, **kwargs):
        has_column = self._meta_has_school_column()
        was_unset = has_column and self.school_id is None
        self.validate_school_consistency()
        if has_column and self.school_id is None:
            self._fill_missing_school()
        if was_unset and self.school_id is not None:
            # A partial save that fills the column has to write it too, or the
            # value is computed and then silently dropped.
            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'school' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['school']
        return super().save(*args, **kwargs)


class SchoolDerivedMixin(SchoolConsistentModel):
    """Fills a denormalised `school` from a related object when not set explicitly.

    These models carry their own school column because their path to a tenant
    can be NULL (a school-wide SubjectSchedule has neither offering nor class
    group) or does not exist at all (Attachment's GenericForeignKey). The column
    still has to be *right*, so rather than making every call site remember it,
    each model names where it can be derived from and this fills it in on save.

    `SCHOOL_DERIVED_FROM` is a tuple of lookup paths tried in order; the first
    one that resolves to a school wins. Order them by authority, not by
    convenience: the row the record actually belongs to comes before whoever
    happened to create it.

    **A user is never a reliable source.** `CustomUser.school` is nullable so
    that `createsuperuser` works, and superusers legitimately have none — so any
    tuple whose only entry is an actor FK has a hole in it exactly when a
    superuser acts. That is a NOT NULL IntegrityError, i.e. a 500, on a routed
    endpoint. Every list here must either end in a source that cannot be NULL,
    or the caller must pass `school` explicitly.
    """

    SCHOOL_DERIVED_FROM: tuple = ()

    class Meta:
        abstract = True

    def _derive_school_id(self):
        for path in self.SCHOOL_DERIVED_FROM:
            obj = self
            for part in path.split('__'):
                obj = getattr(obj, part, None)
                if obj is None:
                    break
            school_id = school_id_of(obj)
            if school_id:
                return school_id
        return None

    def _fill_missing_school(self):
        derived = self._derive_school_id()
        if derived is None:
            raise SchoolDerivationError(
                f'{type(self).__name__}.school is not set and could not be '
                f'derived from {self.SCHOOL_DERIVED_FROM or "()"}. Pass '
                f'school=... explicitly. (Deriving from a user fails for '
                f'superusers, who have no school by design.)'
            )
        self.school_id = derived
