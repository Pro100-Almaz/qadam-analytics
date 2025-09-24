from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.authentication.models import Teacher

class ClassRoom(models.Model):
    name = models.CharField(max_length=100, help_text="Optional classroom or location info")
    capacity = models.PositiveIntegerField(default=1)
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        related_name='classrooms',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="School year this classroom assignment applies to"
    )

    def __str__(self):
        return f"{self.name}"


class AcademicYear(models.Model):
    year = models.CharField(max_length=40) # 2024/2025

    def __str__(self):
        return self.year


class Subject(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('planned', 'Planned'),
        ('disabled', 'Disabled'),
        ('archived', 'Archived'),
    )

    LANGUAGE_CHOICES = (
        ('kaz', 'KAZ'),
        ('rus', 'RUS'),
        ('eng', 'ENG')
    )
    language_group = models.CharField(max_length=20, choices=LANGUAGE_CHOICES, default='KAZ')
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='disabled')

    progress = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Progress percentage (0–100)"
    )
    average_points = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Current points earned (≤ maximum_points)"
    )
    maximum_points = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
        help_text="Total possible points"
    )

    teacher = models.ForeignKey(
        'authentication.Teacher',
        related_name='taught_subjects',
        help_text="Teacher responsible for this lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='subjects_adder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who added this subject"
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        related_name="subjects",
        on_delete=models.PROTECT,
        help_text="School year for this subject"
    )

    def __str__(self):
        return f"{self.name}"

    def update_progress(self, completed_units: int, total_units: int) -> None:
        """
        Given how many units (e.g., lessons, assignments) are done vs. total,
        recompute and save the `progress` percentage.
        """
        if total_units <= 0:
            self.progress = 0
        else:
            self.progress = min(
                100,
                max(0, int((completed_units / total_units) * 100))
            )
        self.save(update_fields=['progress'])

    def record_score(self, points_earned: int) -> None:
        """
        Set average_points (e.g. after an exam), validating against bounds.
        """
        if points_earned < 0:
            raise ValueError("Points must be non-negative")
        if points_earned > self.maximum_points:
            raise ValueError(f"Cannot exceed maximum points ({self.maximum_points})")
        self.average_points = points_earned
        self.save(update_fields=['average_points'])


class QuarterGrader(models.Model):
    subject            = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="quarters")
    quarter            = models.PositiveSmallIntegerField()
    average_points     = models.PositiveIntegerField(default=0)
    cumulative_points  = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('subject', 'quarter')
        ordering = ['quarter']

    def __str__(self):
        return f"Q{self.quarter}: {self.average_points}/{self.subject.maximum_points}"




