from django import forms
from .models import Lesson, LessonGroup, Topic


class DateInput(forms.DateInput):
    input_type = 'date'


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            "title", "description", "subject",
            "average_points", "maximum_points",
            "status", "quarter", "group", "unit"
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
            "unit": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1, "max": 4,
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

class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ['title', 'weight']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter topic title',
            }),
            'weight': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'step': 0.1,
            }),
        }

class SubtopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ['parent', 'title', 'weight']
        widgets = {
            'parent': forms.Select(attrs={
                'class': 'form-control',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter subtopic title',
            }),
            'weight': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'step': 0.1,
            }),
        }
    def __init__(self, *args, **kwargs):
        lesson = kwargs.pop('lesson', None)
        super().__init__(*args, **kwargs)
        if lesson:
            self.fields['parent'].queryset = lesson.topics.filter(parent__isnull=True)