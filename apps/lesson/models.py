from django.db import models, transaction
from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Exists, OuterRef
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from simple_history.models import HistoricalRecords

from apps.home.models import ClassGroup, SubjectOffering, TeachingAssignment
from core.models import (
    SchoolConsistentModel, SchoolDerivedMixin, SoftDeleteMixin,
    live_unique_constraint,
)
from core.tenancy import SchoolScopedManager


class Lesson(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'offering__school'

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


class Topic(SoftDeleteMixin, SchoolConsistentModel):
    SCHOOL_PATH = 'lesson__offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('lesson', 'parent')

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
        constraints = [
            live_unique_constraint(
                fields=['lesson', 'parent', 'title'],
                name='topic_unique_live_lesson_parent_title',
            ),
        ]
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


class TopicGrade(SoftDeleteMixin, SchoolConsistentModel):
    SCHOOL_PATH = 'topic__lesson__offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('topic', 'student')

    topic = models.ForeignKey(Topic, related_name='grades', on_delete=models.CASCADE)
    student = models.ForeignKey('authentication.Student', on_delete=models.CASCADE)
    grade = models.FloatField(default=0, help_text="Percent or points scored in this topic (0-100)")
    comment = models.TextField(blank=True)
    comment_selected = models.BooleanField(default=False)
    history = HistoricalRecords()

    class Meta:
        constraints = [
            live_unique_constraint(
                fields=['topic', 'student'],
                name='topicgrade_unique_live_topic_student',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'topic'], name='idx_topicgrade_student_topic'),
        ]


class MergedLessonComment(SoftDeleteMixin, SchoolDerivedMixin, models.Model):
    SCHOOL_PATH = 'school'
    SCHOOL_DERIVED_FROM = ('lesson__offering', 'student__user')
    SCHOOL_CONSISTENT_FIELDS = ('lesson', 'student')

    # `lesson` and `student` are both nullable, so there is no reliable join
    # path to a school.
    school = models.ForeignKey(
        'authentication.School', related_name='merged_lesson_comments',
        on_delete=models.PROTECT,
    )
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


class QuarterGradeSnapshot(SchoolConsistentModel):
    SCHOOL_PATH = 'offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('student', 'offering')
    objects = SchoolScopedManager()

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
        unique_together = ['student', 'offering', 'quarter']
        indexes = [
            models.Index(fields=['student', 'offering']),
            models.Index(fields=['offering', 'quarter']),
        ]

    @property
    def academic_year(self):
        """Derived from the offering — a snapshot belongs to its offering's year."""
        return self.offering.academic_year

    @property
    def academic_year_id(self):
        return self.offering.academic_year_id

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("QuarterGradeSnapshot cannot be updated after creation.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.offering} Q{self.quarter}: {self.percentage}%"


class SubjectSchedule(SoftDeleteMixin, SchoolDerivedMixin, models.Model):
    SCHOOL_PATH = 'school'
    SCHOOL_DERIVED_FROM = ('offering', 'class_group')
    #: Both are nullable — a school-wide schedule has neither, which the
    #: skip-None rule allows. Only a *disagreement* is rejected.
    SCHOOL_CONSISTENT_FIELDS = ('offering', 'class_group')

    # Both `offering` and `class_group` are nullable — school-wide schedules
    # have neither. 8 such rows exist today; scoping by join would make them
    # invisible to every school, so the row carries its own tenant key.
    school = models.ForeignKey(
        'authentication.School', related_name='subject_schedules',
        on_delete=models.PROTECT,
    )
    SUBJECT_CHOICE = 'subject'
    OTHER_CHOICE   = 'other'
    SCHEDULE_CHOICES = [
        (SUBJECT_CHOICE, "Subject"),
        (OTHER_CHOICE, "Other"),
    ]
    offering = models.ForeignKey(
        SubjectOffering,
        on_delete=models.CASCADE,
        related_name='schedules',
        null=True,
        blank=True
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.CASCADE,
        related_name='schedules',
        null=True,
    )
    description = models.TextField(blank=True, null=True)
    quarter = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])

    class Meta:
        constraints = [
            live_unique_constraint(
                fields=['offering', 'quarter'],
                name='subjectschedule_unique_live_offering_quarter',
            ),
        ]

    def __str__(self):
        if self.offering:
            return f"{self.offering} - {self.quarter}"
        return f"{self.description} - {self.quarter}"


class ScheduleSession(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'schedule__school'

    schedule = models.ForeignKey(
        SubjectSchedule,
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    time_start = models.TimeField()
    time_end = models.TimeField()

    weekday = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(6)])

    class Meta:
        constraints = [
            live_unique_constraint(
                fields=['schedule', 'time_start', 'time_end', 'weekday'],
                name='schedulesession_unique_live_slot',
            ),
        ]
        ordering        = ['schedule', 'weekday', 'time_start', 'time_end']


class ScheduleAttendance(SoftDeleteMixin, SchoolConsistentModel):
    SCHOOL_PATH = 'session__schedule__school'
    SCHOOL_CONSISTENT_FIELDS = ('student', 'session')

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

    # Who wrote the current status, and when. Null on rows saved before these
    # columns existed (spec 0004). Deliberately outside SCHOOL_CONSISTENT_FIELDS:
    # admin roles may act across schools.
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        constraints = [
            # One record per lesson slot. POST upserts against this, so a
            # re-saved register updates rows instead of being refused (0004).
            live_unique_constraint(
                fields=['session', 'student', 'date'],
                name='scheduleattendance_one_per_slot',
            ),
        ]


class Homework(SoftDeleteMixin, SchoolConsistentModel):
    SCHOOL_PATH = 'offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('offering', 'teaching_assignment')

    description = models.TextField()
    offering = models.ForeignKey(SubjectOffering, on_delete=models.CASCADE, related_name='homeworks')
    #: SET_NULL (spec 0013): a homework outlives the teacher's assignment to
    #: the offering, with its grades and files.
    teaching_assignment = models.ForeignKey(
        TeachingAssignment, on_delete=models.SET_NULL, related_name='homeworks',
        null=True, blank=True,
    )
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

    # Every Homework is mirrored by one SubjectAssignment of category
    # `homework` (spec 0005), kept in step here rather than in signals.
    # `sync=False` is for apps.lesson.homework_sync itself.

    def save(self, *args, sync=True, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if sync:
                from apps.lesson import homework_sync
                homework_sync.assignment_from_homework(self)

    def delete(self, *args, sync=True, user=None, **kwargs):
        """Soft delete. `sync=False` leaves the SubjectAssignment mirror alone.

        The stored attachment files stay until the homework is purged — see
        `remove_homework_files` below.
        """
        return super().delete(*args, user=user, extras=sync, **kwargs)

    @classmethod
    def soft_delete_extra(cls, pks):
        """A homework leaves with its SubjectAssignment mirror (spec 0005).

        The mirror is found by `detail_id`, not by an FK, so the walker would
        never reach it on its own. Its SubjectGrades follow by CASCADE.
        """
        from apps.home.models import AssignmentCategory, SubjectAssignment
        yield SubjectAssignment, SubjectAssignment._base_manager.filter(
            category__code=AssignmentCategory.HOMEWORK,
            detail_id__in=pks, is_deleted=False,
        ).values_list('pk', flat=True)


@receiver(pre_delete, sender=Homework, dispatch_uid='homework_remove_files')
def remove_homework_files(sender, instance, **kwargs):
    """Drop a purged homework's stored files once the purge commits (AC-8).

    Only a hard delete sends `pre_delete`, so a soft-deleted homework keeps its
    files. `pre_delete` rather than `post_delete`: the Attachment rows go in
    the same cascade, before the homework row, so they have to be read now.
    The files themselves go on commit, so a purge that rolls back loses
    nothing. `_base_manager`: a purge runs from the admin trash, whose scope
    is the school, but the rows are found by id.
    """
    from apps.achievement.models import Attachment
    files = [
        attachment.file
        for attachment in Attachment._base_manager.filter(
            content_type=ContentType.objects.get_for_model(Homework),
            object_id=instance.pk,
        )
    ]

    def remove():
        for file in files:
            file.delete(save=False)
    transaction.on_commit(remove)


class HomeworkGrade(SoftDeleteMixin, SchoolConsistentModel):
    SCHOOL_PATH = 'homework__offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('homework', 'student')

    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey('authentication.Student', on_delete=models.CASCADE, related_name='homework_grades')
    grade = models.PositiveIntegerField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            live_unique_constraint(
                fields=['homework', 'student'],
                name='homeworkgrade_unique_live_homework_student',
            ),
        ]

    def save(self, *args, sync=True, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if sync:
                from apps.lesson import homework_sync
                homework_sync.subject_grade_from_homework_grade(self)

    def delete(self, *args, sync=True, user=None, **kwargs):
        """`sync=False` leaves the SubjectGrade mirror alone."""
        return super().delete(*args, user=user, extras=sync, **kwargs)

    @classmethod
    def soft_delete_extra(cls, pks):
        """A homework grade leaves with its SubjectGrade mirror (spec 0005)."""
        from apps.home.models import AssignmentCategory, SubjectGrade
        mirrored = cls._base_manager.filter(
            pk__in=pks,
            homework_id=OuterRef('assignment__detail_id'),
            student_id=OuterRef('student_id'),
        )
        yield SubjectGrade, SubjectGrade._base_manager.filter(
            Exists(mirrored),
            assignment__category__code=AssignmentCategory.HOMEWORK,
            is_deleted=False,
        ).values_list('pk', flat=True)
