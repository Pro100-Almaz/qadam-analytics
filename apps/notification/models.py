from django.conf import settings
from django.db import models
from django.db.models import ForeignKey, OneToOneField

from apps.authentication.models import Parent, CustomUser
from apps.lesson.models import Lesson
from core.settings import AUTH_USER_MODEL


class Notification(models.Model):
    ACTION_REGISTER = 'register'
    ACTION_LOGIN = 'login'
    ACTION_GRADING = 'grading'
    ACTION_PSYCHOLOGICAL_STATE = 'psychological_state'

    ACTION_CHOICES = [
        (ACTION_REGISTER, 'Registered'),
        (ACTION_LOGIN, 'Login'),
        (ACTION_GRADING, 'Grading'),
        (ACTION_PSYCHOLOGICAL_STATE, 'Psychological_state'),
    ]
    user = ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='notifications',
        on_delete=models.CASCADE,
        null=False,
        blank=False
    )

    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default=ACTION_REGISTER)
    send_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.action} - {self.send_time}"
        # return f"{self.user} - {self.send_time}"



class RegisterNotify(models.Model):
    notification = OneToOneField(Notification, on_delete=models.CASCADE)

    def get_message(self):
        return "User registered successfully"

class LoginNotify(models.Model):
    notification = OneToOneField(Notification, on_delete=models.CASCADE)

    def get_message(self):
        return "User logged successfully"

class GradingNotify(models.Model):
    notification = OneToOneField(Notification, on_delete=models.CASCADE)
    lesson = ForeignKey(Lesson, related_name='lessons', on_delete=models.CASCADE)
    parent = ForeignKey(Parent, on_delete=models.CASCADE, blank=True, null=True)

    def get_message(self):
        return f"The grade for the lesson '{self.lesson.title}' has been released"


class PsychologicalNotify(models.Model):
    notification = OneToOneField(Notification, on_delete=models.CASCADE)
    parent = ForeignKey(Parent, on_delete=models.CASCADE, blank=True, null=True)
    psychologist = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=False,
        blank=False
    )

    def get_message(self):
        return f"{self.psychologist.username} updated the information about psychological state"
