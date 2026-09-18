"""The one import-time-queryset guard that is about the product, not a tool.

A queryset built in a **class body** is evaluated at import, with no request
and no school scope. Under 'enforce' that raises during ``django.setup()``;
under 'off'/'warn' it silently bakes an **unscoped** queryset that every school
then sees for the life of the process, because DRF's ``RelatedField`` re-chains
a QuerySet rather than re-entering the manager.

The gate for that is one CI step — ``SCHOOL_SCOPE_MODE=enforce manage.py
check`` — which fails on both shapes with the offending file and line in the
traceback. It replaced a 430-line AST linter that checked the same two shapes
less thoroughly: the boot catches *any* import-time scoped query, not only the
two the linter knew how to pattern-match.

What the boot cannot assert is the fix staying in place in a process where the
modules are already imported — which is what this module pins.
"""


def test_the_admin_forms_declare_their_tenant_fks():
    """Regression guard on the sites that used to crash `django.setup()`.

    `MajorClassGroupForm.academic_year` and `StudentAdminForm`'s three FKs were
    left to `Meta.fields`, so ModelFormMetaclass resolved their managers at
    class definition — under 'enforce' that raised before any system check
    could run. Assigning `self.fields[...].queryset` in `__init__` does **not**
    fix it; the metaclass has already run. `declared_fields` is exactly what
    `fields_for_model` consults to skip a field, so asserting on it is
    asserting the actual mechanism.
    """
    from apps.authentication.admin import ParentAdminForm, StudentAdminForm
    from apps.home.admin import MajorClassGroupForm

    assert 'academic_year' in MajorClassGroupForm.declared_fields
    for name in ('school_group', 'academic_year', 'subjects', 'class_group'):
        assert name in StudentAdminForm.declared_fields, name
    assert 'students' in ParentAdminForm.declared_fields

    # Declared is necessary but not sufficient — they must carry no baked
    # queryset either.
    for form in (MajorClassGroupForm, StudentAdminForm, ParentAdminForm):
        for name, field in form.declared_fields.items():
            if hasattr(field, 'queryset'):
                assert field.queryset is None, f'{form.__name__}.{name}'
