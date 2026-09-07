from django import forms
from apps.home.models import Subject, ClassGroup, AcademicYear
from django.contrib.auth import get_user_model

User = get_user_model()


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