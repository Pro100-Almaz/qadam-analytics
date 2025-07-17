from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.authentication.models import Teacher

class ClassRoom(models.Model):
    name = models.CharField(max_length=100, help_text="Optional classroom or location info")
    capacity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.name}"


class Subject(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('planned', 'Planned'),
        ('disabled', 'Disabled'),
        ('archived', 'Archived'),
    )

    name = models.CharField(max_length=100, help_text="Subject taught in the lesson")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='disabled')

    progress = models.PositiveIntegerField(default=0, help_text="Progress of the lesson")
    average_points = models.PositiveIntegerField(default=1, help_text="Grade of the lesson")
    maximum_points = models.PositiveIntegerField(default=100, help_text="Maximum points of the lesson")



    teacher = models.ForeignKey(
        'authentication.Teacher',
        # limit_choices_to={'role': 'teacher'},
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

    classroom = models.ForeignKey(
        ClassRoom,
        related_name='classroom',
        help_text="Classroom of the lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.name}"


class QuarterGrader(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    quarter = models.PositiveIntegerField(default=1)

    average_points = models.PositiveIntegerField(default=1, help_text="Grade of the lesson")
    cummulative_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.average_points}%"



