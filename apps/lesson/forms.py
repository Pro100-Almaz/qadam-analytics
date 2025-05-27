from django import forms
from .models import Lesson, LessonGroup


class DateInput(forms.DateInput):
    input_type = 'date'


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            "title", "description", "subject",
            "average_points", "maximum_points",
            "status", "quarter", "group",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Введите тему урока",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Введите подробное описание",
            }),
            "subject": forms.Select(attrs={"class": "form-control"}),
            "average_points": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
            }),
            "maximum_points": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
            }),
            "status": forms.Select(attrs={"class": "form-control"}),
            "quarter": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1, "max": 4,
            }),
            "group": forms.Select(attrs={"class": "form-control"}),
        }


class LessonGroupForm(forms.ModelForm):
    name = forms.CharField(
        label="Group Name",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Enter new group name'
            }
        )
    )

    class Meta:
        model = LessonGroup
        fields = ['name'] 