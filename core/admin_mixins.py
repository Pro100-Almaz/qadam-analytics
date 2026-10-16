"""Admin support for school scoping.

Most of the admin narrows for free: `ModelAdmin.get_queryset()`,
`formfield_for_foreignkey`, `raw_id_fields` and autocomplete all go through the
model's default manager, which is already scoped. This mixin covers the parts a
manager cannot.

**Stamping `school` on new rows.** Models that carry their own `school` column
have it `NOT NULL`, and the admin's add form does not ask for it — so a plain
`save_model` would raise. Most of these models can derive it (SchoolDerivedMixin),
but `ClassGroup` cannot: it declares no `SCHOOL_DERIVED_FROM` — `grade_level`
is a shared model, and its `academic_year` is `SET_NULL`, so neither is a source
that always resolves. Creating a подгруппа in the admin is the concrete case.

The scope can now always supply the answer: `/admin/` resolves to exactly one
school (the header switcher's, defaulting to the acting user's own), never to
the cross-school sentinel. The fallback below survives only for the case where
no school exists at all.

**Models whose default manager is unscoped.** `CustomUser.objects` is global by
design — `ModelBackend.authenticate` calls it before anyone knows who the user
is — so it is the one model the admin does *not* narrow for free, and the user
changelist showed every tenant. That was consistent while the admin was `ALL`;
under a switcher it silently breaks the promise the header makes. So this mixin
re-applies the scope to those models explicitly, both in the changelist and in
every FK picker that points at one.
"""

from django.core.exceptions import FieldDoesNotExist

from core.tenancy import (
    SchoolScopedManagerMixin,
    apply_school_scope,
    get_active_school,
)


def has_unscoped_default_manager(model):
    """A scoped model whose `objects` deliberately is not scoped.

    Exactly `CustomUser` today (see `core.checks.UNSCOPED_DEFAULT_MANAGER`),
    but derived rather than hardcoded so a second one cannot be added without
    the admin following.
    """
    if getattr(model, 'SCHOOL_PATH', None) is None:
        return False
    return not isinstance(model._default_manager, SchoolScopedManagerMixin)


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

        The active scope is the answer. It names one school on every admin
        request now, so the `request.user` fallback below is unreachable in
        practice — it is kept for the one state that can still produce no
        scope, a brand-new install with no School rows at all, where it is
        equally None and the NOT NULL error is the honest outcome.

        This used to fall back to the acting user's school under `ALL`, which
        meant a superuser browsing school B and clicking Add wrote a school A
        row without saying so. The switcher is what removed that.
        """
        scope = get_active_school()
        if isinstance(scope, int):
            return scope
        return getattr(request.user, 'school_id', None)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if has_unscoped_default_manager(self.model):
            qs = apply_school_scope(qs, self.model)
        return qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Pin the `school` picker to the active school, and narrow the rest.

        Every FK picker narrows for free: `ForeignKey.formfield()`
        resolves `_default_manager`, which is scoped. A picker onto `CustomUser`
        does the same thing and gets the global manager, so `Student.user` would
        offer the other school's people — the exact mixing the composite FKs in
        §7 exist to catch at the far end.
        """
        target = db_field.remote_field.model
        scope = get_active_school()

        if db_field.name == 'school' and 'queryset' not in kwargs:
            # The switcher is the only place a school is chosen. Leaving the
            # full list here would let a superuser scoped to A create a row in
            # B from the add form — the switcher would still say A, and the
            # row would be somewhere else. Kept visible rather than excluded:
            # `get_exclude` fights every ModelAdmin that names `school` in
            # `fieldsets`, and seeing the tenant on the form is the point.
            if isinstance(scope, int):
                kwargs['queryset'] = target.objects.filter(pk=scope)
                kwargs['initial'] = scope
            return super().formfield_for_foreignkey(db_field, request, **kwargs)

        if 'queryset' not in kwargs and has_unscoped_default_manager(target):
            kwargs['queryset'] = apply_school_scope(
                target._default_manager.all(), target,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if self._school_field(obj) is not None and obj.school_id is None:
            obj.school_id = self.school_for_request(request)
        super().save_model(request, obj, form, change)


class SoftDeleteAdminMixin:
    """Mix into the ModelAdmin of every soft-deletable model (spec 0013).

    * The changelist shows live rows already: it reads the default manager.
    * Delete and the "delete selected" action soft-delete and stamp
      `deleted_by` with the acting user (AC-9). Rows come back from the trash
      (`core.admin_trash`), not from here.
    * The confirmation page lists the tree the soft-delete walker will stamp,
      not the one Django's hard-delete Collector would remove, since those
      differ: SET_NULL children stay, and `soft_delete_extra` mirrors go too.

    Put it before `ModelAdmin` in the bases. A subclass that overrides
    `delete_model` / `delete_queryset` must call `super()` to reach it.
    `core.tests.test_admin_trash` fails for an in-scope admin without it.
    """

    #: Rows of one model listed under one root on the confirmation page; the
    #: rest are counted. An offering's tree can run to thousands of grades.
    DELETE_PREVIEW_LIMIT = 20

    def delete_model(self, request, obj):
        obj.delete(user=request.user)

    def delete_queryset(self, request, queryset):
        from core.soft_delete import soft_delete
        soft_delete(queryset, user=request.user)

    def get_deleted_objects(self, objs, request):
        """`(tree, model_count, perms_needed, protected)`, as Django returns it."""
        from django.db.models.deletion import ProtectedError

        from core.soft_delete import collect

        objs = list(objs)
        try:
            found = collect(objs)
        except ProtectedError as exc:
            return [], {}, set(), [
                self._describe_row(request, obj) for obj in exc.protected_objects
            ]

        model_count, perms_needed = {}, set()
        for model, pks in found.items():
            model_count[model._meta.verbose_name_plural] = len(pks)
            model_admin = self.admin_site._registry.get(model)
            if model_admin is not None and not model_admin.has_delete_permission(request):
                perms_needed.add(model._meta.verbose_name)

        tree = []
        for index, obj in enumerate(objs):
            tree.append(self._describe_row(request, obj))
            if index < self.DELETE_PREVIEW_LIMIT:
                children = self._describe_children(request, obj)
                if children:
                    tree.append(children)
        return tree, model_count, perms_needed, []

    def _describe_children(self, request, obj):
        from core.soft_delete import collect

        own = obj._meta.concrete_model
        lines = []
        for model, pks in collect([obj]).items():
            pks = pks - {obj.pk} if model is own else pks
            if not pks:
                continue
            shown = model._base_manager.filter(pk__in=pks).order_by('pk')
            for row in shown[:self.DELETE_PREVIEW_LIMIT]:
                lines.append(self._describe_row(request, row))
            hidden = len(pks) - self.DELETE_PREVIEW_LIMIT
            if hidden > 0:
                lines.append(f'… {hidden} more {model._meta.verbose_name_plural}')
        return lines

    def _describe_row(self, request, obj):
        from django.urls import NoReverseMatch, reverse
        from django.utils.html import format_html
        from django.utils.text import capfirst

        opts = obj._meta
        model_admin = self.admin_site._registry.get(type(obj))
        if model_admin is not None and model_admin.has_change_permission(request, obj):
            try:
                url = reverse(
                    f'{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change',
                    args=[obj.pk],
                )
            except NoReverseMatch:
                pass
            else:
                return format_html(
                    '{}: <a href="{}">{}</a>', capfirst(opts.verbose_name), url, obj,
                )
        return format_html('{}: {}', capfirst(opts.verbose_name), obj)
