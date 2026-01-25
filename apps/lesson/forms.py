from django import forms
from .models import Lesson, Topic


class DateInput(forms.DateInput):
    input_type = 'date'


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            "offering",
            "title",
            "description",
            "date",
            "status",
            "quarter",
            "unit",
            "order",
        ]
        widgets = {
            "offering": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Введите тему урока",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Введите подробное описание",
            }),
            "date": DateInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "quarter": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1, "max": 4,
            }),
            "unit": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1, "max": 15,
            }),
            "order": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
            }),
        }


class LessonGroupForm(forms.Form):
    """Placeholder form for lesson grouping functionality."""
    pass

class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ['title', 'weight', 'comment_template']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter topic title',
            }),
            'comment_template': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Шаблон для комментария',
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
        fields = ['parent', 'title', 'weight', 'comment_template']
        widgets = {
            'parent': forms.Select(attrs={
                'class': 'form-control',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter subtopic title',
            }),
            'comment_template': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Шаблон для комментария',
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

        if not self.instance or not self.instance.pk:
            if 'weight' in self.fields:
                del self.fields['weight']
            self.fields['parent'].required = True