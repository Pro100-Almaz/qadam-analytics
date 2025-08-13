from django import forms
from .models import Subject
from django.contrib.auth import get_user_model

User = get_user_model()

class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = [
            "name",
            "status",
            "maximum_points",
            "teacher",
            "academic_year",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Напишите назание предмета",
            }),
            "status": forms.Select(attrs={
                "class": "form-control",
            }),

            "maximum_points": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
            }),
            "teacher": forms.Select(attrs={
                "class": "form-control",
            }),
            "academic_year": forms.Select(attrs={
                "class": "form-control",
            }),
        }