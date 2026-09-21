from django import forms
from apps.home.models import Subject, ClassGroup, AcademicYear
from django.contrib.auth import get_user_model

User = get_user_model()


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
    """Dropdown over *both* categories — classes and Подгруппы alike."""
    kwargs.setdefault("queryset", ClassGroup.objects.select_related(
        "grade_level", "academic_year"
    ).order_by("-academic_year__year", "category", "grade_level__number", "letter"))
    kwargs["form_class"] = ClassGroupChoiceField
    return db_field.formfield(**kwargs)


class SubjectForm(forms.ModelForm):
    # Additional fields for creating SubjectOffering
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.order_by('-year'),
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
        label="Учебный год"
    )
    class_groups = forms.ModelMultipleChoiceField(
        queryset=ClassGroup.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-control",
            "size": "5",
        }),
        label="Классы",
        help_text="Выберите классы для этого предмета (удерживайте Ctrl для выбора нескольких)"
    )

    class Meta:
        model = Subject
        fields = [
            "name",
            "language_group",
            "status",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Напишите название предмета",
            }),
            "language_group": forms.Select(attrs={
                "class": "form-control",
            }),
            "status": forms.Select(attrs={
                "class": "form-control",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter class groups by selected academic year if available
        if 'academic_year' in self.data:
            try:
                year_id = int(self.data.get('academic_year'))
                self.fields['class_groups'].queryset = ClassGroup.objects.filter(
                    academic_year_id=year_id
                ).order_by('grade_level__number', 'letter')
            except (ValueError, TypeError):
                pass
        else:
            # Default to active year's class groups
            active_year = AcademicYear.objects.filter(is_active=True).first()
            if active_year:
                self.fields['class_groups'].queryset = ClassGroup.objects.filter(
                    academic_year=active_year
                ).order_by('grade_level__number', 'letter')
                self.fields['academic_year'].initial = active_year