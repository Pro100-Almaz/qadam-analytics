from django.db import models
from django.utils import timezone


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def all_with_deleted(self):
        return super().get_queryset()

    def deleted_only(self):
        return super().get_queryset().filter(is_deleted=True)


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

    objects = SoftDeleteManager()
    all_objects = models.Manager()

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


class SchoolDerivedMixin(models.Model):
    """Fills a denormalised `school` from a related object when not set explicitly.

    These models carry their own school column because their path to a tenant
    can be NULL (a school-wide SubjectSchedule has neither offering nor class
    group) or does not exist at all (Attachment's GenericForeignKey). The column
    still has to be *right*, so rather than making every call site remember it,
    each model names where it can be derived from and this fills it in on save.

    `SCHOOL_DERIVED_FROM` is a tuple of lookup paths tried in order; the first
    one that resolves to something with a school wins. If none do, the caller
    must supply `school` explicitly — the NOT NULL constraint will say so.
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
            if obj is not None:
                school_id = getattr(obj, 'school_id', None)
                if school_id:
                    return school_id
        return None

    def save(self, *args, **kwargs):
        if self.school_id is None:
            derived = self._derive_school_id()
            if derived is not None:
                self.school_id = derived
                update_fields = kwargs.get('update_fields')
                if update_fields is not None and 'school' not in update_fields:
                    kwargs['update_fields'] = list(update_fields) + ['school']
        return super().save(*args, **kwargs)
