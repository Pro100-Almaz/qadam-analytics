from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator, MaxValueValidator
from simple_history.models import HistoricalRecords

from apps.authentication.models import CustomUser
from apps.home.models import ClassGroup, Subject, SubjectOffering, TeachingAssignment
from core.models import SoftDeleteMixin


class Lesson(SoftDeleteMixin, models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('delayed', 'Delayed'),
        ('on schedule', 'On Schedule'),
    )

    offering = models.ForeignKey(
        'home.SubjectOffering',
        on_delete=models.CASCADE,
        related_name='lessons',
    )

    title = models.CharField(max_length=255, help_text="Title of the lesson")
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the lesson"
    )
    date = models.DateField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['date', 'order']
        verbose_name = "Lesson"
        verbose_name_plural = "Lessons"
        indexes = [
            models.Index(fields=['offering', 'quarter'], name='idx_lesson_offering_qtr'),
            models.Index(fields=['date'], name='idx_lesson_date'),
            models.Index(fields=['offering', 'date'], name='idx_lesson_offering_date'),
        ]

    def __str__(self):
        return f"{self.title} ({self.offering})"

    def calculate_student_grade(self, student, grades_map=None):
        """
        Calculate weighted grade for a student for this lesson.

        Args:
            student: Student instance
            grades_map: Optional dict mapping (topic_id, student_id) -> grade.
                       If provided, uses this instead of querying the database.
        """
        if grades_map is None:
            # Fetch all grades for this student and lesson in one query
            topic_grades = TopicGrade.objects.filter(
                topic__lesson=self,
                student=student
            ).values('topic_id', 'grade')
            grades_map = {(tg['topic_id'], student.id): tg['grade'] for tg in topic_grades}

        total_grade = 0
        for topic in self.topics.filter(parent__isnull=True):
            grade = grades_map.get((topic.id, student.id), 0)
            total_grade += grade * (float(topic.weight) / 100)
        return total_grade

    @classmethod
    def calculate_grades_bulk(cls, lessons, students):
        """
        Calculate grades for multiple lessons and students efficiently.

        Args:
            lessons: Queryset or list of Lesson instances
            students: Queryset or list of Student instances

        Returns:
            dict mapping (lesson_id, student_id) -> grade
        """
        from django.db.models import F

        lesson_ids = [l.id for l in lessons]
        student_ids = [s.id for s in students]

        # Fetch all topic grades in one query
        all_grades = TopicGrade.objects.filter(
            topic__lesson_id__in=lesson_ids,
            student_id__in=student_ids
        ).values('topic_id', 'topic__lesson_id', 'student_id', 'grade')

        # Build grades map: (topic_id, student_id) -> grade
        grades_map = {}
        for g in all_grades:
            grades_map[(g['topic_id'], g['student_id'])] = g['grade']

        # Fetch all parent topics with weights in one query
        topics_by_lesson = {}
        parent_topics = Topic.objects.filter(
            lesson_id__in=lesson_ids,
            parent__isnull=True
        ).values('id', 'lesson_id', 'weight')

        for t in parent_topics:
            if t['lesson_id'] not in topics_by_lesson:
                topics_by_lesson[t['lesson_id']] = []
            topics_by_lesson[t['lesson_id']].append(t)

        # Calculate grades for all lesson-student pairs
        results = {}
        for lesson in lessons:
            lesson_topics = topics_by_lesson.get(lesson.id, [])
            for student in students:
                total_grade = 0
                for topic in lesson_topics:
                    grade = grades_map.get((topic['id'], student.id), 0)
                    total_grade += grade * (float(topic['weight']) / 100)
                results[(lesson.id, student.id)] = total_grade

        return results

    @classmethod
    def construct_comment_bulk(cls, lessons, students, grades_map):
        merged_comments = {
            (m.lesson_id, m.student_id): [m.lesson.title, m.comment_text]
            for m in MergedLessonComment.objects.filter(lesson__in=lessons, student__in=students)
        }

        results = {
            key: {
                'title': value[0],
                'comment': value[1],
                'grade': grades_map.get(key, 0)
            } for key, value in merged_comments.items()
        }
        return results


class Topic(models.Model):
    lesson = models.ForeignKey(
        Lesson,
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
    order = models.PositiveIntegerField(
        default=0,
        help_text="Sequence order for accumulation logic (lower = earlier)"
    )
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
    history = HistoricalRecords()

    class Meta:
        unique_together = ('lesson', 'parent', 'title')
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.title} ({self.weight}%)"

    def calculate_subtopics_grade(self, student):
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


class TopicGrade(models.Model):
    topic = models.ForeignKey(Topic, related_name='grades', on_delete=models.CASCADE)
    student = models.ForeignKey('authentication.Student', on_delete=models.CASCADE)
    grade = models.FloatField(default=0, help_text="Percent or points scored in this topic (0-100)")
    comment = models.TextField(blank=True)
    comment_selected = models.BooleanField(default=False)
    history = HistoricalRecords()

    class Meta:
        unique_together = ('topic', 'student')
        indexes = [
            models.Index(fields=['student', 'topic'], name='idx_topicgrade_student_topic'),
        ]


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
    is_merged = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.student} - {self.lesson}: {self.comment_text[:30]}"


class QuarterGradeSnapshot(models.Model):
    student = models.ForeignKey(
        'authentication.Student', on_delete=models.PROTECT,
        related_name='grade_snapshots',
    )
    offering = models.ForeignKey(
        'home.SubjectOffering', on_delete=models.PROTECT,
        related_name='grade_snapshots',
    )
    quarter = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear', on_delete=models.PROTECT,
    )
    final_grade = models.DecimalField(max_digits=5, decimal_places=2)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    letter_grade = models.CharField(max_length=2, blank=True)
    lesson_count = models.PositiveIntegerField()
    graded_lesson_count = models.PositiveIntegerField()
    frozen_at = models.DateTimeField(auto_now_add=True)
    frozen_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='frozen_snapshots',
    )

    class Meta:
        unique_together = ['student', 'offering', 'quarter', 'academic_year']
        indexes = [
            models.Index(fields=['student', 'academic_year']),
            models.Index(fields=['offering', 'quarter']),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("QuarterGradeSnapshot cannot be updated after creation.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.offering} Q{self.quarter}: {self.percentage}%"


class SubjectSchedule(models.Model):
    offering = models.ForeignKey(
        SubjectOffering,
        on_delete=models.CASCADE,
        related_name='schedules',
    )
    quarter = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])

    class Meta:
        unique_together = ['offering', 'quarter']

    def __str__(self):
        return f"{self.offering} - {self.quarter}"


class ScheduleSession(models.Model):
    schedule = models.ForeignKey(
        SubjectSchedule,
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    order = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    weekday = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(6)])

    class Meta:
        unique_together = ['schedule', 'order', 'weekday']


class ScheduleAttendance(models.Model):
    ATTENDANCE_CHOICES = (
        ('present', 'Present'),
        ('absent', 'Absent'),
    )

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='attendances',
    )
    session = models.ForeignKey(
        ScheduleSession,
        on_delete=models.CASCADE,
        related_name='attendances',
    )
    date = models.DateField()
    status = models.CharField(choices=ATTENDANCE_CHOICES, max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)


class Homework(models.Model):
    description = models.TextField()
    offering = models.ForeignKey(SubjectOffering, on_delete=models.CASCADE, related_name='homeworks')
    teaching_assignment = models.ForeignKey(TeachingAssignment, on_delete=models.CASCADE, related_name='homeworks')
    max_grade = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    due_date = models.DateField()
    is_active = models.BooleanField(default=False)

    attachments = GenericRelation(
        'achievement.Attachment',
        content_type_field='content_type',
        object_id_field='object_id',
        related_query_name='homework',
    )

    created_at = models.DateTimeField(auto_now_add=True)


class HomeworkGrade(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey('authentication.Student', on_delete=models.CASCADE, related_name='homework_grades')
    grade = models.PositiveIntegerField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('homework', 'student')
