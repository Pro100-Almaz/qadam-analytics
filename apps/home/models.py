from django.db import models
from django.conf import settings


class Subject(models.Model):
    name = models.CharField(max_length=100, help_text="Subject taught in the lesson")
    status = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}"


class ClassRoom(models.Model):
    name = models.CharField(max_length=100, help_text="Optional classroom or location info")
    capacity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.name}"


class Lesson(models.Model):
    title = models.CharField(max_length=255, help_text="Title of the lesson")
    description = models.TextField(blank=True, help_text="Detailed description of the lesson")

    # Assuming you are using a custom user model that includes a 'teacher' role.
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        limit_choices_to={'role': 'teacher'},
        related_name='lessons',
        help_text="Teacher responsible for this lesson"
    )

    subject = models.ForeignKey(
        Subject,
        on_delete=models.DO_NOTHING,
        related_name='lessons',
        help_text="Subject of the lesson"

    )
    classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.DO_NOTHING,
        related_name='lessons',
        help_text="Classroom of the lesson"
    )

    grade = models.PositiveIntegerField(default=1, help_text="Grade of the lesson")
    progress = models.PositiveIntegerField(default=0, help_text="Progress of the lesson")

    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        limit_choices_to={'role': 'student'},
        related_name='lessons_attended',
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'updated_at']
        verbose_name = "Lesson"
        verbose_name_plural = "Lessons"

    def __str__(self):
        return f"{self.title}"
