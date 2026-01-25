from django import forms
from .models import Subject
from django.contrib.auth import get_user_model

User = get_user_model()

class SubjectForm(forms.ModelForm):
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
                "placeholder": "Напишите назание предмета",
            }),
            "language_group": forms.Select(attrs={
                "class": "form-control",
            }),
            "status": forms.Select(attrs={
                "class": "form-control",
            }),
        }