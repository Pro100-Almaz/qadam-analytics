from django.conf import settings
from django.db import models


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        REGISTER = 'register', 'Registration'
        LOGIN = 'login', 'Login'
        GRADING = 'grading', 'Grading'
        PSYCHOLOGICAL = 'psychological_state', 'Psychological State'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
    )
    title = models.CharField(max_length=255, default='')
    message = models.TextField(default='')
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f"{self.user} - {self.type} - {self.created_at}"
