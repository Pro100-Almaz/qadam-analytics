from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class LessonGroup(models.Model):
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
    unit = models.PositiveIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(15)
        ],
        help_text="Unit of the lesson"
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

    def calculate_student_grade(self, student):
        """Calculate weighted grade for a student for this lesson."""

        def sum_topic(topic):
            # Get student's grade for this topic, if exists
            tg = TopicGrade.objects.filter(topic=topic, student=student).first()
            my_grade = tg.grade if tg else 0

            # If topic has subtopics, sum them by weight; else, use own grade
            # children = list(topic.subtopics.all()) # children = subtopics of the topic
            # print(children)
            # if children:
            #     total = 0
            #     for sub in children:
            #         print(sub)
            #         total += sum_topic(sub) * (sub.weight / 100)
            #     return total
            # else:
            return my_grade

        total_grade = 0
        for topic in self.topics.filter(parent__isnull=True):
            total_grade += (sum_topic(topic) * (float(topic.weight) / 100))
        return total_grade


class Topic(models.Model):
    lesson = models.ForeignKey(
        'Lesson',
        related_name='topics',
        on_delete=models.CASCADE
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='subtopics',
        on_delete=models.CASCADE
    )
    title = models.CharField(max_length=255)
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.0,
        help_text="Percent weight in lesson (must sum to 100% for all siblings under same parent)"
    )
    comment_template = models.CharField(
        max_length=255,
        default='',
    )


    def calculate_subtopics_grade(self, student):
        # Compute a weighted grade (0-100) across immediate subtopics for the given student
        # If there are no subtopics, return 0 – caller may set topic-level grade explicitly
        subtopics_qs = self.subtopics.all()
        if not subtopics_qs.exists():
            return 0

        grades_with_weights = TopicGrade.objects.filter(
            topic__in=subtopics_qs,
            student=student
        ).select_related('topic').values_list('grade', 'topic__weight')

        weighted_sum = 0.0
        total_weight = 0.0
        for grade_value, weight_value in grades_with_weights:
            try:
                grade_float = float(grade_value)
            except (TypeError, ValueError):
                grade_float = 0.0
            try:
                weight_float = float(weight_value)
            except (TypeError, ValueError):
                weight_float = 0.0
            weighted_sum += grade_float * weight_float
            total_weight += weight_float

        return (weighted_sum / total_weight) if total_weight > 0 else 0.0

    def __str__(self):
        return f"{self.title} ({self.weight}%)"
    class Meta:
        unique_together = ('lesson', 'title')



class TopicGrade(models.Model):
    topic = models.ForeignKey(Topic, related_name='grades', on_delete=models.CASCADE)
    student = models.ForeignKey('authentication.Student', on_delete=models.CASCADE)
    grade = models.FloatField(default=0, help_text="Percent or points scored in this topic (0-100)")
    comment = models.TextField(blank=True)
    comment_selected = models.BooleanField(default=False)

    class Meta:
        unique_together = ('topic', 'student')


class MergedLessonComment(models.Model):
    lesson = models.ForeignKey(
        Lesson,
        related_name='lesson_comment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    student = models.ForeignKey(
        'authentication.Student',
        related_name='lesson_comment',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    comment_text = models.TextField(help_text="Template comment text")

    def __str__(self):
        return f"{self.student} - {self.lesson}: {self.comment_text[:30]}"