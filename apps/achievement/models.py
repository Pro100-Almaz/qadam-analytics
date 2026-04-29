from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Achievement(models.Model):
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} - {self.get_category_display()} ({self.academic_year})"


class ReadingEntry(models.Model):
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

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'month', 'title']

    def __str__(self):
        return f"{self.student} - {self.title}"


class ClubEntry(models.Model):
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

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'month', 'club_name']

    def __str__(self):
        return f"{self.student} - {self.club_name} ({self.month}/{self.academic_year})"
