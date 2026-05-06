from django.db import models
from django.conf import settings
from simple_history.models import HistoricalRecords
from apps.authentication.models import Teacher


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
    letter = models.CharField(default="A", max_length=10)

    def __str__(self):
        return f"{self.grade_level}{self.letter} ({self.academic_year})"


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
    academic_year = models.ForeignKey(
        AcademicYear,
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

    class Meta:
        unique_together = ('subject', 'class_group', 'academic_year')

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
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name='homeroom_assignments',
    )

    class Meta:
        unique_together = ('class_group', 'academic_year')

    def __str__(self):
        return f"{self.teacher} → {self.class_group} ({self.academic_year})"


class Enrollment(models.Model):
    """Tracks which class a student belongs to in a given academic year."""
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
    academic_year = models.ForeignKey(
        AcademicYear,
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
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'academic_year'],
                condition=models.Q(status='active'),
                name='unique_active_enrollment_per_year'
            )
        ]
        ordering = ['-academic_year__year', 'class_group']
        indexes = [
            models.Index(fields=['academic_year', 'status'], name='idx_enrollment_year_status'),
            models.Index(fields=['student', 'status'], name='idx_enrollment_student_status'),
        ]

    def __str__(self):
        return f"{self.student} - {self.class_group} ({self.status})"

    @classmethod
    def get_current_enrollment(cls, student):
        """Get the student's current active enrollment."""
        return cls.objects.filter(
            student=student,
            status='active',
            academic_year__is_active=True
        ).select_related('class_group', 'academic_year').first()

    @classmethod
    def get_students_in_class(cls, class_group, academic_year=None, status='active'):
        """Get all students enrolled in a class group."""
        qs = cls.objects.filter(class_group=class_group, status=status)
        if academic_year:
            qs = qs.filter(academic_year=academic_year)
        return qs.select_related('student', 'student__user')

    @classmethod
    def enroll_student(cls, student, class_group, academic_year, start_date=None):
        """Enroll a student in a class group, deactivating any existing active enrollment."""
        from django.utils import timezone

        # Deactivate existing active enrollment for the same year
        cls.objects.filter(
            student=student,
            academic_year=academic_year,
            status='active'
        ).update(status='transferred', end_date=timezone.now().date())

        # Create new enrollment
        return cls.objects.create(
            student=student,
            class_group=class_group,
            academic_year=academic_year,
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




