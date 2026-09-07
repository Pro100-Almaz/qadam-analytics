from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.conf import settings
from simple_history.models import HistoricalRecords
from apps.authentication.models import Teacher, Student


class AcademicYear(models.Model):
    year = models.CharField(max_length=40)  # 2024/2025
    is_active = models.BooleanField(default=False)
    archived = models.BooleanField(default=True)

    q1_start = models.DateField(null=True, blank=True)
    q1_end = models.DateField(null=True, blank=True)
    q2_start = models.DateField(null=True, blank=True)
    q2_end = models.DateField(null=True, blank=True)
    q3_start = models.DateField(null=True, blank=True)
    q3_end = models.DateField(null=True, blank=True)
    q4_start = models.DateField(null=True, blank=True)
    q4_end = models.DateField(null=True, blank=True)

    @property
    def current_quarter(self):
        from django.utils import timezone
        today = timezone.localdate()
        for q in [1, 2, 3, 4]:
            start = getattr(self, f'q{q}_start')
            end = getattr(self, f'q{q}_end')
            if start and end and start <= today <= end:
                return q
        return None

    @property
    def quarters(self):
        result = []
        for q in [1, 2, 3, 4]:
            start = getattr(self, f'q{q}_start')
            end = getattr(self, f'q{q}_end')
            result.append({
                'quarter': q,
                'start': start.isoformat() if start else None,
                'end': end.isoformat() if end else None,
            })
        return result

    def __str__(self):
        return self.year


class GradeLevel(models.Model):
    number = models.PositiveSmallIntegerField()

    def __str__(self):
        return str(self.number)


class ClassGroup(models.Model):
    MAJOR_CHOICE = 'major'
    MINOR_CHOICE = 'minor'
    CATEGORY_CHOICES = (
        (MAJOR_CHOICE, 'Major'),
        (MINOR_CHOICE, 'Minor'),
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        related_name='class_groups',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    grade_level = models.ForeignKey(
        GradeLevel,
        related_name='class_groups',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    letter = models.CharField(default="A", max_length=50)
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=10, default=MAJOR_CHOICE)

    class Meta:
        verbose_name = "Класс"
        verbose_name_plural = "Классы"

    @property
    def short_name(self):
        """`7A` for a class; a subgroup without a grade level is just its name."""
        if self.grade_level_id:
            return f"{self.grade_level}{self.letter}"
        return self.letter

    def __str__(self):
        return f"{self.short_name} ({self.academic_year})"

    @property
    def is_major(self):
        return self.category == self.MAJOR_CHOICE

    @property
    def is_minor(self):
        return self.category == self.MINOR_CHOICE


class MinorClassGroupManager(models.Manager):
    """Restricts every query — and every create — to the minor category."""

    def get_queryset(self):
        return super().get_queryset().filter(category=ClassGroup.MINOR_CHOICE)

    def create(self, **kwargs):
        kwargs['category'] = ClassGroup.MINOR_CHOICE
        return super().create(**kwargs)


class MinorClassGroup(ClassGroup):
    """Подгруппа — a minor class group, e.g. an English or elective subgroup.

    A proxy over ClassGroup so subgroups get their own admin section and their
    own queries while sharing the model, enrollments and subject offerings of
    regular (major) classes.
    """
    objects = MinorClassGroupManager()

    class Meta:
        proxy = True
        verbose_name = "Подгруппа"
        verbose_name_plural = "Подгруппы"

    def save(self, *args, **kwargs):
        self.category = ClassGroup.MINOR_CHOICE
        return super().save(*args, **kwargs)


class ClassGroupCollection(models.Model):
    """A constellation: one class and the подгруппы bound to it.

    Each major class group has at most one constellation, which is created the
    first time a subgroup is bound and then stays — emptying it leaves it in
    place, ready to be filled again. Subgroups are shared rather than owned:
    «English Advanced» can sit in 7A's constellation and 7B's at the same time.
    """
    major = models.OneToOneField(
        ClassGroup,
        on_delete=models.CASCADE,
        related_name='collection',
        limit_choices_to={'category': ClassGroup.MAJOR_CHOICE},
        verbose_name="Класс",
    )
    minor_groups = models.ManyToManyField(
        ClassGroup,
        related_name='collections',
        limit_choices_to={'category': ClassGroup.MINOR_CHOICE},
        blank=True,
        verbose_name="Подгруппы",
    )

    class Meta:
        verbose_name = "Созвездие класса"
        verbose_name_plural = "Созвездия классов"

    def __str__(self):
        return f"Созвездие {self.major}"

    @classmethod
    def get_minor_groups(cls, class_group):
        """The subgroups bound to `class_group`, empty list if it has none.

        Reads through the constellation so a prefetched one costs no query;
        use `minor_groups_of()` when a queryset is what you need.
        """
        collection = cls.of(class_group)
        return list(collection.minor_groups.all()) if collection else []

    @staticmethod
    def minor_groups_of(class_group):
        """Queryset of the подгруппы bound to a class group (instance or id)."""
        return ClassGroup.objects.filter(collections__major=class_group)

    @classmethod
    def of(cls, class_group):
        """The constellation of a class group, or None — never creates one."""
        if not class_group or not class_group.pk:
            return None
        return getattr(class_group, 'collection', None)

    @classmethod
    def bind_minor_groups(cls, class_group, minor_groups):
        """Bind exactly `minor_groups` to `class_group`.

        The constellation is created on demand by the first binding. Clearing
        the selection empties it but keeps it — an existing constellation is
        never deleted from here.
        """
        collection = cls.of(class_group)

        if collection is None:
            if not minor_groups:
                return None
            collection = cls.objects.create(major=class_group)

        collection.minor_groups.set(minor_groups or [])
        return collection


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

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='subjects_adder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who added this subject"
    )

    def __str__(self):
        return f"{self.name}"


class SubjectOffering(models.Model):
    """
    The central entity: "Math for 7A in 2025/2026"

    Ties together: Subject, ClassGroup, AcademicYear, teachers, lessons, grades.
    Everything on a subject page filters by this offering.
    """
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='offerings'
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.CASCADE,
        related_name='subject_offerings'
    )

    # Grading configuration for this offering
    max_points = models.PositiveIntegerField(default=100)
    GRADING_STRATEGY_CHOICES = [
        ('average', 'Average of all scores'),
        ('weighted', 'Weighted by assessment type'),
        ('cumulative', 'Cumulative points'),
    ]
    grading_strategy = models.CharField(
        max_length=20,
        choices=GRADING_STRATEGY_CHOICES,
        default='average'
    )

    @property
    def academic_year(self):
        """Derived from the class group — an offering runs in its class's year."""
        return self.class_group.academic_year

    @property
    def academic_year_id(self):
        return self.class_group.academic_year_id

    def __str__(self):
        return f"{self.subject} - {self.class_group} ({self.academic_year})"

    def get_students(self):
        """Get all active students enrolled in this offering's class group."""
        return Enrollment.get_students_in_class(
            self.class_group,
            self.academic_year,
            status='active'
        )

    def get_lessons(self):
        """Get all lessons for this offering ordered by date and order."""
        return self.lessons.all().order_by('date', 'order')

    def get_teachers(self):
        """Get all teachers assigned to this offering."""
        return self.teaching_assignments.select_related('teacher', 'teacher__user')

    def get_primary_teacher(self):
        """Get the primary teacher for this offering."""
        assignment = self.teaching_assignments.filter(role='primary').first()
        return assignment.teacher if assignment else None


class TeachingAssignment(models.Model):
    """Assigns teachers to a SubjectOffering with specific roles."""
    ROLE_CHOICES = [
        ('primary', 'Primary Teacher'),
        ('assistant', 'Assistant Teacher'),
        ('substitute', 'Substitute'),
    ]

    offering = models.ForeignKey(
        SubjectOffering,
        on_delete=models.CASCADE,
        related_name='teaching_assignments'
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.CASCADE,
        related_name='teaching_assignments'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='primary')

    class Meta:
        unique_together = ('offering', 'teacher')

    def __str__(self):
        return f"{self.teacher} - {self.offering} ({self.get_role_display()})"


class HomeroomTeacherAssignment(models.Model):
    """Links a homeroom teacher to a class group for an academic year."""
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.CASCADE,
        related_name='homeroom_assignments',
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.CASCADE,
        related_name='homeroom_assignments',
    )

    class Meta:
        unique_together = ('class_group',)

    @property
    def academic_year(self):
        """Derived from the class group — a class group belongs to one year."""
        return self.class_group.academic_year

    @property
    def academic_year_id(self):
        return self.class_group.academic_year_id

    def __str__(self):
        return f"{self.teacher} → {self.class_group} ({self.academic_year})"


class Enrollment(models.Model):
    """Tracks which class a student belongs to in a given academic year.

    A student may hold at most one active enrollment in a *major* class group
    per academic year, but any number of active *minor* group enrollments.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('transferred', 'Transferred'),
        ('graduated', 'Graduated'),
        ('withdrawn', 'Withdrawn'),
        ('on_leave', 'On Leave'),
    ]

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['-class_group__academic_year__year', 'class_group']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'class_group'],
                condition=models.Q(status='active'),
                name='unique_active_enrollment_per_class_group'
            )
        ]
        indexes = [
            models.Index(fields=['class_group', 'status'], name='idx_enrollment_class_status'),
            models.Index(fields=['student', 'status'], name='idx_enrollment_student_status'),
        ]

    @property
    def academic_year(self):
        """Derived from the class group — a class group belongs to one year."""
        return self.class_group.academic_year

    @property
    def academic_year_id(self):
        return self.class_group.academic_year_id

    def __str__(self):
        return f"{self.student} - {self.class_group} ({self.status})"

    def clean(self):
        super().clean()
        self.validate_single_major()

    def save(self, *args, **kwargs):
        self.validate_single_major()
        return super().save(*args, **kwargs)

    def validate_single_major(self):
        """A student can hold only one active major enrollment per academic year."""
        if self.status != 'active' or not self.class_group_id:
            return

        class_group = self.class_group
        if not class_group.is_major:
            return

        conflict = type(self).objects.filter(
            student_id=self.student_id,
            status='active',
            class_group__category=ClassGroup.MAJOR_CHOICE,
            class_group__academic_year_id=class_group.academic_year_id,
        ).exclude(pk=self.pk).exclude(class_group_id=class_group.pk).first()

        if conflict:
            raise ValidationError({
                'class_group': (
                    f"{self.student} is already enrolled in the major class group "
                    f"{conflict.class_group}; a student can have only one major "
                    f"class group per academic year."
                )
            })

    @classmethod
    def get_current_enrollment(cls, student):
        """Get the student's current active enrollment in a major class group."""
        return cls.objects.filter(
            student=student,
            status='active',
            class_group__category=ClassGroup.MAJOR_CHOICE,
            class_group__academic_year__is_active=True
        ).select_related('class_group', 'class_group__academic_year').first()

    @classmethod
    def get_current_minor_enrollments(cls, student):
        """Get the student's active enrollments in minor class groups."""
        return cls.objects.filter(
            student=student,
            status='active',
            class_group__category=ClassGroup.MINOR_CHOICE,
            class_group__academic_year__is_active=True
        ).select_related('class_group', 'class_group__academic_year')

    @classmethod
    def get_students_in_class(cls, class_group, academic_year=None, status='active'):
        """Get all students enrolled in a class group."""
        qs = cls.objects.filter(class_group=class_group, status=status)
        if academic_year:
            qs = qs.filter(class_group__academic_year=academic_year)
        return qs.select_related('student', 'student__user')

    @classmethod
    def enroll_student(cls, student, class_group, academic_year=None, start_date=None):
        """Enroll a student in a class group.

        Enrolling in a major class group replaces the student's existing active
        major enrollment for that academic year. Minor class groups are additive —
        a student can be enrolled in as many of them as needed.
        """
        from django.utils import timezone

        if academic_year is None:
            academic_year = class_group.academic_year

        existing = cls.objects.filter(
            student=student,
            class_group=class_group,
            status='active',
        ).first()
        if existing:
            return existing

        if class_group.is_major:
            # Deactivate existing active major enrollment for the same year
            cls.objects.filter(
                student=student,
                status='active',
                class_group__category=ClassGroup.MAJOR_CHOICE,
                class_group__academic_year=academic_year,
            ).update(status='transferred', end_date=timezone.now().date())

        # Create new enrollment
        return cls.objects.create(
            student=student,
            class_group=class_group,
            status='active',
            start_date=start_date or timezone.now().date()
        )


class QuarterGrader(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="quarters")
    quarter = models.PositiveSmallIntegerField()
    average_points = models.PositiveIntegerField(default=0)
    cumulative_points = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('subject', 'quarter')
        ordering = ['quarter']

    def __str__(self):
        return f"Q{self.quarter}: avg={self.average_points}"


class SubjectAssignment(models.Model):
    CATEGORY_CHOICES = (
        ('lesson', 'Lesson'),
        ('exam', 'Exam'),
        ('final', 'Final'),
    )

    title = models.TextField()
    offering = models.ForeignKey(SubjectOffering, on_delete=models.CASCADE, related_name="assignments")
    max_grade = models.PositiveIntegerField()
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=50, default='lesson')
    date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)


class SubjectGrade(models.Model):
    assignment = models.ForeignKey(SubjectAssignment, on_delete=models.CASCADE, related_name="grades")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="grades")
    grade = models.PositiveIntegerField(null=True, blank=True)
    comments = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('assignment', 'student')
        ordering = ['student']


class QuarterGrade(models.Model):
    grade = models.PositiveIntegerField(validators=[MinValueValidator(2), MaxValueValidator(5)])
    quarter = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="quarter_grades")
    offering = models.ForeignKey(SubjectOffering, on_delete=models.CASCADE, related_name="quarter_grades")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'offering', 'quarter')
        ordering = ['quarter', 'student']
