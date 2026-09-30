from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.conf import settings
from simple_history.models import HistoricalRecords
from apps.authentication.models import Teacher, Student
from core.models import SchoolConsistentModel, SchoolDerivedMixin
from core.tenancy import SchoolScopedManager, SchoolScopedManagerMixin


class AcademicYear(models.Model):
    """A school year and its quarter boundaries. One row PER SCHOOL.

    §1a briefly made this shared — one 2025/2026 row for everybody — on the
    grounds that both schools follow the same national calendar. Reversed
    2026-09-21: sharing the row also shares `q1_start … q4_end`, `is_active`
    and the rollover day, so the two schools could never diverge on term dates
    without undoing it, and it is cheaper to split while school #2 has almost
    no data than after a year of grades hangs off the shared row.

    What that costs, stated so it is findable: `filter(is_active=True).first()`
    is no longer a global singleton. Inside a request it is correct — the
    scoped manager narrows it to one school — and outside one it raises under
    `SCHOOL_SCOPE_MODE=enforce` rather than silently picking a tenant. The
    `/admin/` case is what made this safe to do at all: since §9a a superuser
    is scoped to exactly one school there, so the seven admin call sites see
    one candidate row, not four.
    """

    SCHOOL_PATH = 'school'
    objects = SchoolScopedManager()

    #: Root: a year belongs to its school directly. PROTECT, never CASCADE —
    #: deleting a tenant must not silently take its calendar and every grade
    #: that hangs off it.
    school = models.ForeignKey(
        'authentication.School', related_name='academic_years',
        on_delete=models.PROTECT,
    )
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

    class Meta:
        constraints = [
            # §7: one `2025/2026` per school. Was a plain `unique(year)` while
            # the row was shared; the school column is what lets both tenants
            # name the same year again.
            models.UniqueConstraint(
                fields=['school', 'year'],
                name='academicyear_unique_year_per_school',
            ),
            # `filter(is_active=True).first()` is used as a per-school
            # singleton in ~24 places. Without this it is nondeterministic the
            # moment a rollover leaves two rows active, and the failure is a
            # silently wrong year rather than an error.
            models.UniqueConstraint(
                fields=['school'],
                condition=models.Q(is_active=True),
                name='academicyear_one_active_per_school',
            ),
            # §7 layer 3: the composite FKs in
            # home/0040_composite_school_fks reference (id, school_id), and
            # Postgres will only point a foreign key at a UNIQUE index. `id`
            # is already unique on its own, so this adds no new rule about the
            # data — it exists solely to give that FK something to reference.
            models.UniqueConstraint(
                fields=['id', 'school'],
                name='academicyear_id_school_unique',
            ),
        ]
        verbose_name = 'Учебный год'
        verbose_name_plural = 'Учебные годы'

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


class ClassGroup(SchoolDerivedMixin, models.Model):
    SCHOOL_PATH = 'school'
    #: A class group in one school cannot sit in another school's year —
    #: which is exactly what the §1b split had to unpick by hand.
    SCHOOL_CONSISTENT_FIELDS = ('academic_year',)
    objects = SchoolScopedManager()

    # No SCHOOL_DERIVED_FROM: `academic_year` is shared and carries no school,
    # and `grade_level` is shared too — so there is nothing to derive from.
    # Every creation site must pass `school=` explicitly; SchoolDerivationError
    # says so by name if one forgets.

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
    # Root: `academic_year` is SET_NULL/nullable, so a class group cannot
    # reliably reach a school by join — it carries its own.
    school = models.ForeignKey(
        'authentication.School', related_name='class_groups',
        on_delete=models.PROTECT,
    )

    class Meta:
        constraints = [
            # §7 layer 3: the composite FKs in
            # home/0040_composite_school_fks reference (id, school_id), and
            # Postgres will only point a foreign key at a UNIQUE index. `id`
            # is already unique on its own, so this adds no new rule about the
            # data — it exists solely to give that FK something to reference.
            models.UniqueConstraint(
                fields=['id', 'school'],
                name='classgroup_id_school_unique',
            ),
        ]
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


class MinorClassGroupManager(SchoolScopedManagerMixin, models.Manager):
    """Restricts every query — and every create — to the minor category.

    The scope mixin goes first so the school filter composes on top of the
    category filter rather than replacing it.
    """

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

    # Declared again rather than inherited: core.checks walks concrete and proxy
    # models alike, and an explicit path is what it reports against.
    SCHOOL_PATH = 'school'

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

    SCHOOL_PATH = 'major__school'
    objects = SchoolScopedManager()

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
    SCHOOL_PATH = 'school'
    objects = SchoolScopedManager()

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
    # Root: each school owns its own subject catalogue.
    school = models.ForeignKey(
        'authentication.School', related_name='subjects',
        on_delete=models.PROTECT,
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

    class Meta:
        constraints = [
            # §7 layer 3: the composite FKs in
            # home/0040_composite_school_fks reference (id, school_id), and
            # Postgres will only point a foreign key at a UNIQUE index. `id`
            # is already unique on its own, so this adds no new rule about the
            # data — it exists solely to give that FK something to reference.
            models.UniqueConstraint(
                fields=['id', 'school'],
                name='subject_id_school_unique',
            ),
        ]

    def __str__(self):
        return f"{self.name}"


class SubjectOffering(SchoolDerivedMixin, models.Model):
    """
    The central entity: "Math for 7A in 2025/2026"

    Ties together: Subject, ClassGroup, AcademicYear, teachers, lessons, grades.
    Everything on a subject page filters by this offering.
    """

    SCHOOL_PATH = 'school'
    SCHOOL_DERIVED_FROM = ('class_group',)
    #: The hub, and the one place cross-tenant mixing actually happens:
    #: school A's Subject offered to school B's ClassGroup. Also the
    #: composite FK pair in the database (§7 layer 3).
    SCHOOL_CONSISTENT_FIELDS = ('subject', 'class_group')
    objects = SchoolScopedManager()

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
    # Hub: everything in apps/lesson reaches a school through this row, and it
    # is where cross-tenant mixing would happen (school A's Subject + school B's
    # ClassGroup). Derived from class_group on save; see Phase 6.
    school = models.ForeignKey(
        'authentication.School', related_name='subject_offerings',
        on_delete=models.PROTECT,
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


class TeachingAssignment(SchoolConsistentModel):
    """Assigns teachers to a SubjectOffering with specific roles."""

    SCHOOL_PATH = 'offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('offering', 'teacher')
    objects = SchoolScopedManager()

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

    def delete(self, *args, **kwargs):
        # Homework cascades from here, but its SubjectAssignment mirror hangs
        # off the offering and would be left pointing at nothing (spec 0005).
        # Deleting each homework through its own delete() takes the mirror and
        # the stored attachment files with it.
        Homework = apps.get_model('lesson', 'Homework')
        with transaction.atomic():
            for homework in Homework._base_manager.filter(teaching_assignment=self):
                homework.delete()
            return super().delete(*args, **kwargs)


class HomeroomTeacherAssignment(SchoolConsistentModel):
    """Links a homeroom teacher to a class group for an academic year."""

    SCHOOL_PATH = 'class_group__school'
    SCHOOL_CONSISTENT_FIELDS = ('teacher', 'class_group')
    objects = SchoolScopedManager()

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


class Enrollment(SchoolConsistentModel):
    """Tracks which class a student belongs to in a given academic year.

    A student may hold at most one active enrollment in a *major* class group
    per academic year, but any number of active *minor* group enrollments.
    """

    SCHOOL_PATH = 'class_group__school'
    SCHOOL_CONSISTENT_FIELDS = ('student', 'class_group')
    objects = SchoolScopedManager()

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
    SCHOOL_PATH = 'subject__school'
    objects = SchoolScopedManager()

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="quarters")
    quarter = models.PositiveSmallIntegerField()
    average_points = models.PositiveIntegerField(default=0)
    cumulative_points = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('subject', 'quarter')
        ordering = ['quarter']

    def __str__(self):
        return f"Q{self.quarter}: avg={self.average_points}"


class AssignmentCategory(models.Model):
    """What kind of graded work a SubjectAssignment is: lesson, exam, homework…

    Shared by every school, like GradeLevel: an admin who adds a category adds
    it for all tenants. Rows are managed in /admin/ (spec 0005).

    A category may have a *detail model* — a table holding the fields specific
    to that kind of work. `SubjectAssignment.detail_id` then stores the pk of
    the matching row there. Only `homework` has one today.
    """

    HOMEWORK = 'homework'
    #: What an assignment is when the client does not say.
    DEFAULT = 'lesson'

    #: category code -> 'app_label.Model' of its detail model.
    DETAIL_MODELS = {
        HOMEWORK: 'lesson.Homework',
    }

    #: Codes the code base depends on: never deleted, never renamed.
    SYSTEM_CODES = frozenset(DETAIL_MODELS)

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'assignment categories'

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        """The `lesson` row; recreated if an admin deleted it while unused."""
        category, _ = cls.objects.get_or_create(
            code=cls.DEFAULT, defaults={'name': 'Lesson'},
        )
        return category

    @property
    def is_system(self):
        return self.code in self.SYSTEM_CODES

    @property
    def detail_model(self):
        """The model `detail_id` points into, or None for a plain category."""
        label = self.DETAIL_MODELS.get(self.code)
        return apps.get_model(label) if label else None


class SubjectAssignment(models.Model):
    SCHOOL_PATH = 'offering__school'
    objects = SchoolScopedManager()

    title = models.TextField()
    offering = models.ForeignKey(SubjectOffering, on_delete=models.CASCADE, related_name="assignments")
    max_grade = models.PositiveIntegerField()
    category = models.ForeignKey(
        AssignmentCategory, on_delete=models.PROTECT, related_name='assignments',
    )
    date = models.DateField()

    #: pk of the row in `category.detail_model` that this assignment mirrors —
    #: a Homework id for category `homework`. Not a ForeignKey because the
    #: target table depends on the category, so `validate_detail()` does the
    #: checks a real FK would.
    detail_id = models.PositiveIntegerField(null=True, blank=True)
    #: False for a draft. Synced from Homework.is_active; students, parents and
    #: analytics never see an inactive assignment.
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # One assignment per detail row: a Homework is mirrored once.
            models.UniqueConstraint(
                fields=['category', 'detail_id'],
                condition=models.Q(detail_id__isnull=False),
                name='subjectassignment_unique_detail',
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def is_homework(self):
        return self.category.code == AssignmentCategory.HOMEWORK

    @property
    def details(self):
        """The detail row (e.g. the Homework) or None."""
        model = self.category.detail_model
        if model is None or self.detail_id is None:
            return None
        return model._base_manager.filter(pk=self.detail_id).first()

    def validate_detail(self):
        """
        The checks a ForeignKey would give `detail_id` for free.

        Run from save(), not only clean(): DRF and `objects.create()` never call
        full_clean(), so a clean()-only check would guard nothing (see
        core.models.SchoolConsistentModel).
        """
        category = self.category
        model = category.detail_model

        if model is None:
            if self.detail_id is not None:
                raise ValidationError({
                    'detail_id': f'Category "{category.code}" has no detail model, '
                                 f'so detail_id must be empty.'
                })
        else:
            if self.detail_id is None:
                raise ValidationError({
                    'detail_id': f'Category "{category.code}" needs detail_id: '
                                 f'the id of its {model.__name__}.'
                })
            detail = model._base_manager.filter(pk=self.detail_id).first()
            if detail is None:
                raise ValidationError({
                    'detail_id': f'{model.__name__} #{self.detail_id} does not exist.'
                })
            if detail.offering_id != self.offering_id:
                raise ValidationError({
                    'detail_id': f'{model.__name__} #{self.detail_id} belongs to '
                                 f'another subject offering.'
                })

        if self.pk is not None:
            old_category_id = type(self)._base_manager.filter(
                pk=self.pk,
            ).values_list('category_id', flat=True).first()
            if old_category_id is not None and old_category_id != self.category_id:
                old = AssignmentCategory.objects.get(pk=old_category_id)
                if old.detail_model is not None or model is not None:
                    raise ValidationError({
                        'category': f'Cannot change category from "{old.code}" to '
                                    f'"{category.code}": one of them has its own '
                                    f'detail model. Delete and recreate instead.'
                    })

    def clean(self):
        super().clean()
        if self.category_id is not None and self.offering_id is not None:
            self.validate_detail()

    def save(self, *args, sync=True, **kwargs):
        """`sync=False` is for the homework sync itself, so a write never echoes back."""
        self.validate_detail()
        with transaction.atomic():
            super().save(*args, **kwargs)
            if sync and self.is_homework:
                from apps.lesson import homework_sync
                homework_sync.homework_from_assignment(self)

    def delete(self, *args, sync=True, **kwargs):
        with transaction.atomic():
            homework_id = self.detail_id if sync and self.is_homework else None
            result = super().delete(*args, **kwargs)
            if homework_id is not None:
                from apps.lesson import homework_sync
                homework_sync.delete_homework(homework_id)
            return result


class SubjectGrade(SchoolConsistentModel):
    SCHOOL_PATH = 'assignment__offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('assignment', 'student')
    objects = SchoolScopedManager()

    assignment = models.ForeignKey(SubjectAssignment, on_delete=models.CASCADE, related_name="grades")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="grades")
    grade = models.PositiveIntegerField(null=True, blank=True)
    comments = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('assignment', 'student')
        ordering = ['student']

    def save(self, *args, sync=True, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if sync and self.assignment.is_homework:
                from apps.lesson import homework_sync
                homework_sync.homework_grade_from_subject_grade(self)

    def delete(self, *args, sync=True, **kwargs):
        with transaction.atomic():
            if sync and self.assignment.is_homework:
                from apps.lesson import homework_sync
                homework_sync.delete_homework_grade(
                    self.assignment.detail_id, self.student_id,
                )
            return super().delete(*args, **kwargs)


class QuarterGrade(SchoolConsistentModel):
    SCHOOL_PATH = 'offering__school'
    SCHOOL_CONSISTENT_FIELDS = ('student', 'offering')
    objects = SchoolScopedManager()

    grade = models.PositiveIntegerField(validators=[MinValueValidator(2), MaxValueValidator(5)])
    quarter = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="quarter_grades")
    offering = models.ForeignKey(SubjectOffering, on_delete=models.CASCADE, related_name="quarter_grades")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'offering', 'quarter')
        ordering = ['quarter', 'student']
