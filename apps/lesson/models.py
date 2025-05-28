from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class   LessonGroup(models.Model):
    name = models.CharField(max_length=100, help_text="Group of the lessons", default="", null=True, blank=True)

    def __str__(self):
        return f"{self.name}"


class Lesson(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('delayed', 'Delayed'),
        ('on schedule', 'On Schedule'),
    )

    title = models.CharField(max_length=255, help_text="Title of the lesson")
    description = models.TextField(blank=True, help_text="Detailed description of the lesson")

    subject = models.ForeignKey(
        'home.Subject',
        related_name='lesson_subject',
        help_text="Subject of the lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    average_points = models.PositiveIntegerField(default=1, help_text="Grade of the lesson")
    maximum_points = models.PositiveIntegerField(default=100, help_text="Maximum points of the lesson")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    quarter = models.PositiveIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(4)
        ],
        help_text="Quarter of the lesson"
    )
    group = models.ForeignKey(LessonGroup, related_name='lesson_group', on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'updated_at']
        verbose_name = "Lesson"
        verbose_name_plural = "Lessons"

    def __str__(self):
        return f"{self.title}"


class StudentGrade(models.Model):
    lesson = models.ForeignKey(Lesson, related_name='lesson_grade', on_delete=models.DO_NOTHING)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='lesson_student_grade', on_delete=models.DO_NOTHING)
    grade = models.PositiveIntegerField(default=0, help_text="Grade of the lesson")
    points = models.PositiveIntegerField(default=0, help_text="Points of the lesson")

    comment = models.TextField(blank=True, help_text="Comment of the lesson")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.lesson.title} - {self.student}"


class Comment(models.Model):
    lesson = models.ForeignKey(
        Lesson,
        related_name='lesson_comment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    from_points = models.PositiveIntegerField(default=0, help_text="Points of the lesson")
    to_points = models.PositiveIntegerField(default=100, help_text="Points of the lesson")
    comment_text = models.TextField(help_text="Template comment text")

    def __str__(self):
        return f"Comment template for points {self.from_points}-{self.to_points}"
