from django import forms
from .models import Lesson
from django.contrib.auth import get_user_model

User = get_user_model()

class DateInput(forms.DateInput):
    input_type = 'date'

class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ['title', 'description', 'subject']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].queryset = User.objects.filter(role=User.ROLE_TEACHER)

