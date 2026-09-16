"""Form fields shared by the Django admin.

Extracted from the legacy `apps.home.forms` so the admin does not depend on the
retired server-rendered view layer.
"""

from django import forms

from apps.home.models import ClassGroup


def class_group_label(obj):
    """`7A — класс (2025/2026)` / `Шахматы — подгруппа (2025/2026)`."""
    kind = "подгруппа" if obj.is_minor else "класс"
    return f"{obj.short_name} — {kind} ({obj.academic_year})"


class ClassGroupChoiceField(forms.ModelChoiceField):
    """Spells out whether a choice is a class or a subgroup (подгруппа)."""

    def label_from_instance(self, obj):
        return class_group_label(obj)


class ClassGroupMultipleChoiceField(forms.ModelMultipleChoiceField):
    """The multi-select counterpart of ClassGroupChoiceField."""

    def label_from_instance(self, obj):
        return class_group_label(obj)


def class_group_formfield(db_field, **kwargs):
    """Dropdown over *both* categories — classes and Подгруппы alike.

    The queryset is built per call, not at import, so it resolves inside
    whatever school scope is active at the time.
    """
    kwargs.setdefault("queryset", ClassGroup.objects.select_related(
        "grade_level", "academic_year"
    ).order_by("-academic_year__year", "category", "grade_level__number", "letter"))
    kwargs["form_class"] = ClassGroupChoiceField
    return db_field.formfield(**kwargs)
