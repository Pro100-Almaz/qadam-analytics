from django.conf import settings
from django.db import models


class StudentReport(models.Model):
    class Language(models.TextChoices):
        RUSSIAN = 'ru', 'Русский'
        KAZAKH = 'kk', 'Қазақша'
        ENGLISH = 'en', 'English'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        GENERATING = 'generating', 'Generating'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='reports',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
    )
    quarter = models.PositiveSmallIntegerField(
        help_text='Quarter number (1-4)',
    )
    language = models.CharField(
        max_length=2,
        choices=Language.choices,
        default=Language.RUSSIAN,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    report_data = models.JSONField(
        null=True,
        blank=True,
        help_text='Structured report sections as JSON',
    )

    input_snapshot = models.JSONField(
        default=dict,
        help_text='Snapshot of student data sent to AI at generation time',
    )
    model_used = models.CharField(max_length=50, blank=True, default='')
    tokens_used = models.PositiveIntegerField(null=True, blank=True)
    generation_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='generated_reports',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', '-created_at']),
            models.Index(fields=['student', 'academic_year', 'quarter']),
        ]

    def __str__(self):
        return f"Report: {self.student} — {self.academic_year} Q{self.quarter}"
