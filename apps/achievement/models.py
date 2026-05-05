from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from core.models import SoftDeleteMixin


MAX_ATTACHMENT_SIZE_MB = 10
MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_MB * 1024 * 1024


def validate_attachment_size(file):
    if file.size > MAX_ATTACHMENT_SIZE_BYTES:
        from django.core.exceptions import ValidationError
        raise ValidationError(
            f'File size must be less than {MAX_ATTACHMENT_SIZE_MB}MB. '
            f'Current size: {file.size / (1024 * 1024):.1f}MB'
        )


class Attachment(models.Model):
    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('document', 'Document'),
        ('certificate', 'Certificate'),
        ('other', 'Other'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    file = models.FileField(
        upload_to='achievements/attachments/%Y/%m/',
        validators=[validate_attachment_size],
    )
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default='other')
    original_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.original_name} ({self.file_type})"


class Achievement(SoftDeleteMixin, models.Model):
    CATEGORY_CHOICES = [
        ('olympiad', 'Subject Olympiad'),
        ('additional_education', 'Additional Education'),
        ('extracurricular', 'Extracurricular Activity'),
        ('project', 'Project'),
    ]

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='achievements',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='achievements',
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)

    # For olympiad, additional_education, project
    subject = models.ForeignKey(
        'home.Subject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='achievements',
        help_text='Only for olympiad category',
    )
    award_type = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Gold Medal, 1st Place Diploma',
    )
    place = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. City, Regional, National, International',
    )

    # For extracurricular
    role = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Class President, Club Leader',
    )
    duration = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Sep 2025 - May 2026',
    )

    # Common
    description = models.TextField(
        blank=True,
        help_text='Description or result/comments for extracurricular',
    )
    certificate = models.FileField(
        upload_to='achievements/certificates/',
        null=True,
        blank=True,
    )
    attachments = GenericRelation(Attachment)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} - {self.get_category_display()} ({self.academic_year})"


class ReadingEntry(SoftDeleteMixin, models.Model):
    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='reading_entries',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='reading_entries',
    )
    title = models.CharField(max_length=500)
    cover = models.ImageField(
        upload_to='achievements/book_covers/',
        null=True,
        blank=True,
    )
    month = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    pages_read = models.PositiveIntegerField(default=0)
    test_score = models.FloatField(
        null=True,
        blank=True,
        help_text='Test result for this book (0-100)',
    )
    attachments = GenericRelation(Attachment)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'month', 'title']

    def __str__(self):
        return f"{self.student} - {self.title}"


class ClubEntry(SoftDeleteMixin, models.Model):
    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='club_entries',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='club_entries',
    )
    month = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    club_name = models.CharField(max_length=255)
    plan = models.TextField(blank=True)
    criteria = models.TextField(blank=True)
    total_sessions = models.PositiveIntegerField(default=0)
    attended_sessions = models.PositiveIntegerField(default=0)
    comments = models.TextField(blank=True)
    attachments = GenericRelation(Attachment)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'month', 'club_name']

    def __str__(self):
        return f"{self.student} - {self.club_name} ({self.month}/{self.academic_year})"
