from django import forms
from .models import Lesson, Subject, LessonGroup
from django.contrib.auth import get_user_model

User = get_user_model()

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


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = [
            "name",
            "status",
            "progress",
            "average_points",
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
            "average_points": forms.NumberInput(attrs={
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