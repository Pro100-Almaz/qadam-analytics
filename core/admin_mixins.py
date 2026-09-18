"""Admin support for school scoping.

Most of the admin narrows for free: `ModelAdmin.get_queryset()`,
`formfield_for_foreignkey`, `raw_id_fields` and autocomplete all go through the
model's default manager, which is already scoped. This mixin covers the parts a
manager cannot.

**Stamping `school` on new rows.** Models that carry their own `school` column
have it `NOT NULL`, and the admin's add form does not ask for it — so a plain
`save_model` would raise. Most of these models can derive it (SchoolDerivedMixin),
but `ClassGroup` cannot: §1a made `AcademicYear` shared, and `grade_level` was
always shared, so there is nothing left to derive from. Creating a подгруппа in
the admin is the concrete case.

`/admin/` is also where cross-school work happens — superusers resolve to ALL
there, by the decision in §4 — so the scope cannot supply the answer either.
The acting user's own school is the fallback, which is right because it is the
school they work at.
"""

from django.core.exceptions import FieldDoesNotExist

from core.tenancy import get_active_school


class SchoolScopedAdminMixin:
    """Mix into a ModelAdmin whose model carries its own `school` column."""

    def _school_field(self, obj):
        """The model's own `school` column, or None.

        `_meta.fields`, not `_meta.local_fields`: a **proxy** model has no local
        fields at all — they belong to the concrete parent — so a local_fields
        check silently skips every proxy. MinorClassGroup is exactly that, and
        it is the one model that cannot derive its school, so skipping it meant
        creating a подгруппа in the admin raised SchoolDerivationError.
        """
        try:
            field = obj._meta.get_field('school')
        except FieldDoesNotExist:
            return None
        return field if getattr(field, 'concrete', False) else None

    def school_for_request(self, request):
        """A concrete school pk, or None.

        The active scope wins when it names one school. Under `ALL` — which is
        what a superuser gets in the admin — it names none, so fall back to the
        acting user's own school. Phase 7's switcher replaces this fallback with
        an explicit choice.
        """
        scope = get_active_school()
        if isinstance(scope, int):
            return scope
        return getattr(request.user, 'school_id', None)

    def save_model(self, request, obj, form, change):
        if self._school_field(obj) is not None and obj.school_id is None:
            obj.school_id = self.school_for_request(request)
        super().save_model(request, obj, form, change)
