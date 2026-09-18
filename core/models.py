from django.db import models
from django.utils import timezone

from core.tenancy import (
    SchoolDerivationError, SchoolScopedManager, SchoolScopedManagerMixin,
    apply_school_scope,
)


class SoftDeleteManager(models.Manager):
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


class SoftDeleteMixin(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        'authentication.CustomUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    # `objects` first: Django takes the first declared manager as the default,
    # and the default manager is what reverse FKs, M2M and the admin go through.
    objects = ScopedSoftDeleteManager()
    #: Soft-deleted rows included, still school-scoped.
    all_objects = SchoolScopedManager()
    #: Neither filter. Last resort — one word, and greppable.
    unscoped = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])


def school_id_of(obj):
    """The school a related object belongs to, or None.

    Two ways an object reaches a school, and both have to work here: it carries
    its own `school` column, or it declares a `SCHOOL_PATH` to one. Only
    checking for `school_id` was the bug behind an Attachment on a Club — Club
    is scoped by `academic_year__school` and has no column of its own, so the
    attribute lookup came back None and the derivation fell through.

    The walk goes through forward FKs, which Django resolves via `_base_manager`
    — unscoped by design. That is what we want: this is working out *which*
    tenant owns a row, so it must not be filtered by the tenant already active.
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
    for part in parts[:-1]:
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return getattr(obj, 'school_id', None)


class SchoolDerivedMixin(models.Model):
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

    def save(self, *args, **kwargs):
        if self.school_id is None:
            derived = self._derive_school_id()
            if derived is None:
                raise SchoolDerivationError(
                    f'{type(self).__name__}.school is not set and could not be '
                    f'derived from {self.SCHOOL_DERIVED_FROM or "()"}. Pass '
                    f'school=... explicitly. (Deriving from a user fails for '
                    f'superusers, who have no school by design.)'
                )
            self.school_id = derived
            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'school' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['school']
        return super().save(*args, **kwargs)
