from django import forms
from .models import Lesson, Subject
from django.contrib.auth import get_user_model

User = get_user_model()

class DateInput(forms.DateInput):
    input_type = 'date'

class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ['title', 'description', 'subject']


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name', 'status', 'progress', 'teacher', 'classroom']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].queryset = User.objects.filter(role=User.ROLE_TEACHER)

