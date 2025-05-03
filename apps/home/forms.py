from django import forms
from .models import Lesson, Subject
from django.contrib.auth import get_user_model

User = get_user_model()

class DateInput(forms.DateInput):
    input_type = 'date'


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            "title", "description", "subject",
            "average_grade", "maximum_points",
            "status", "quarter", "group",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Enter lesson title",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Enter detailed description",
            }),
            "subject": forms.Select(attrs={"class": "form-control"}),
            "average_grade": forms.NumberInput(attrs={
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


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = [
            "name",
            "status",
            "progress",
            "average_grade",
            "maximum_points",
            "teacher",
            "classroom",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Напишите назание предмета",
            }),
            "status": forms.Select(attrs={
                "class": "form-control",
            }),
            "progress": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
                "max": 100,
            }),
            "average_grade": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
            }),
            "maximum_points": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
            }),
            "teacher": forms.Select(attrs={
                "class": "form-control",
            }),
            "classroom": forms.Select(attrs={
                "class": "form-control",
            }),
        }
