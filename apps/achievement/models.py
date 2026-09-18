import os

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from core.models import SchoolDerivedMixin, SoftDeleteMixin
from core.tenancy import SchoolScopedManager

MAX_ATTACHMENT_SIZE_MB = 10
MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = {
    '.pdf',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
}
IMAGE_ATTACHMENT_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
}


def validate_attachment_size(file):
    if file.size > MAX_ATTACHMENT_SIZE_BYTES:
        raise ValidationError(
            f'File size must not exceed {MAX_ATTACHMENT_SIZE_MB}MB. '
            f'Current size: {file.size / (1024 * 1024):.1f}MB'
        )


def validate_attachment_format(file):
    """Allow PDFs and verified browser-safe images only."""
    extension = os.path.splitext(file.name)[1].lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))
        raise ValidationError(f'Unsupported file format. Allowed formats: {allowed}.')

    try:
        file.seek(0)
        if extension in IMAGE_ATTACHMENT_EXTENSIONS:
            image = Image.open(file)
            image.verify()
        elif extension == '.pdf':
            if file.read(5) != b'%PDF-':
                raise ValidationError('The uploaded file is not a valid PDF document.')
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(
            f'The uploaded {extension[1:].upper()} file is invalid or corrupted.'
        ) from exc
    finally:
        file.seek(0)


class Attachment(SchoolDerivedMixin, models.Model):
    """A file hung off any model by GenericForeignKey.

    `content_object` comes first and `uploaded_by` second, deliberately. The
    attachment belongs to the row it is attached to, so that row is the
    authority on which school owns it; the uploader is only a fallback for a
    content_object whose target has since been deleted.

    Deriving from the uploader *alone* was a live 500: `uploaded_by` is
    SET_NULL, and a superuser has no school by design, so every upload by a
    superuser through the club, achievement or homework endpoints hit the NOT
    NULL constraint. Ordering it this way also closes the milder case — a
    school-A user attaching to a school-B row no longer files the attachment
    under school A, where nobody looking at the row would ever see it.
    """

    SCHOOL_PATH = 'school'
    SCHOOL_DERIVED_FROM = ('content_object', 'uploaded_by')
    objects = SchoolScopedManager()

    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('document', 'Document'),
        ('certificate', 'Certificate'),
        ('other', 'Other'),
    ]

    # A GenericForeignKey has no lookup path, so no join can reach a school —
    # the attachment carries its own tenant key.
    school = models.ForeignKey(
        'authentication.School', related_name='attachments',
        on_delete=models.PROTECT,
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    file = models.FileField(
        upload_to='achievements/attachments/%Y/%m/',
        validators=[validate_attachment_size, validate_attachment_format],
    )
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default='other')
    original_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.original_name} ({self.file_type})"


class Achievement(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'student__user__school'

    CATEGORY_CHOICES = [
        ('olympiad', 'Subject Olympiad'),
        ('additional_education', 'Additional Education'),
        ('extracurricular', 'Extracurricular Activity'),
        ('project', 'Project'),
    ]

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='achievements',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='achievements',
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)

    # For olympiad, additional_education, project
    subject = models.ForeignKey(
        'home.Subject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='achievements',
        help_text='Only for olympiad category',
    )
    award_type = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Gold Medal, 1st Place Diploma',
    )
    place = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. City, Regional, National, International',
    )

    # For extracurricular
    role = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Class President, Club Leader',
    )
    duration = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Sep 2025 - May 2026',
    )

    # Common
    description = models.TextField(
        blank=True,
        help_text='Description or result/comments for extracurricular',
    )
    certificate = models.FileField(
        upload_to='achievements/certificates/',
        null=True,
        blank=True,
    )
    attachments = GenericRelation(Attachment)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} - {self.get_category_display()} ({self.academic_year})"


class ReadingEntry(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'student__user__school'

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='reading_entries',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='reading_entries',
    )
    title = models.CharField(max_length=500)
    cover = models.ImageField(
        upload_to='achievements/book_covers/',
        null=True,
        blank=True,
    )
    month = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    pages_read = models.PositiveIntegerField(default=0)
    test_score = models.FloatField(
        null=True,
        blank=True,
        help_text='Test result for this book (0-100)',
    )
    attachments = GenericRelation(Attachment)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'month', 'title']

    def __str__(self):
        return f"{self.student} - {self.title}"


class ClubEntry(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'student__user__school'

    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='club_entries',
    )
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='club_entries',
    )
    month = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    club_name = models.CharField(max_length=255)
    plan = models.TextField(blank=True)
    criteria = models.TextField(blank=True)
    total_sessions = models.PositiveIntegerField(default=0)
    attended_sessions = models.PositiveIntegerField(default=0)
    comments = models.TextField(blank=True)
    attachments = GenericRelation(Attachment)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'month', 'club_name']

    def __str__(self):
        return f"{self.student} - {self.club_name} ({self.month}/{self.academic_year})"


class Club(SchoolDerivedMixin, SoftDeleteMixin, models.Model):
    """A club. Carries its own school column.

    Since §1a made AcademicYear shared, `academic_year__school` no longer
    reaches a tenant — and `manager` is the only other FK, which is SET_NULL.
    A nullable link in a SCHOOL_PATH becomes an INNER JOIN that drops every
    manager-less club from every school's queryset, so the column is the only
    correct answer.
    """

    SCHOOL_PATH = 'school'
    SCHOOL_DERIVED_FROM = ('manager__user',)

    school = models.ForeignKey(
        'authentication.School', related_name='clubs',
        on_delete=models.PROTECT,
    )

    CLUB_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('deleted', 'Deleted'),
        ('finished', 'Finished'),
    )
    manager = models.ForeignKey(
        'authentication.ClubManager',
        on_delete=models.SET_NULL,
        null=True,
        related_name='clubs',
    )

    academic_year = models.ForeignKey(
        'home.AcademicYear',
        on_delete=models.CASCADE,
        related_name='clubs',
    )
    start_date = models.DateField()
    end_date = models.DateField()

    name = models.CharField(max_length=255)
    plan = models.TextField(blank=True)
    criteria = models.TextField(blank=True)
    members = models.ManyToManyField(
        'authentication.Student',
        blank=True,
        related_name='clubs',
    )
    attachments = GenericRelation(Attachment)

    status = models.CharField(choices=CLUB_STATUS_CHOICES, max_length=50, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['academic_year', 'start_date', 'manager', 'name']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F('start_date')),
                name='club_end_date_on_or_after_start',
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.manager} ({self.start_date}-{self.end_date})"

    def soft_delete(self, user=None):
        self.status = 'deleted'
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=[
            'status', 'is_deleted', 'deleted_at', 'deleted_by',
        ])


class ClubSession(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'club__school'

    WEEKDAY_CHOICES = (
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    )

    club = models.ForeignKey(
        'achievement.Club',
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    weekday = models.CharField(max_length=10, choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=255)

    class Meta:
        ordering = ['weekday', 'start_time', 'id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name='club_session_end_after_start',
            ),
        ]

    def __str__(self):
        return f"{self.club.name}: {self.weekday} {self.start_time}-{self.end_time}"


class ClubAttendance(SoftDeleteMixin, models.Model):
    SCHOOL_PATH = 'session__club__school'

    ATTENDANCE_CHOICES = (
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
    )

    session = models.ForeignKey(
        'achievement.ClubSession',
        on_delete=models.CASCADE,
        related_name='attendances',
    )
    student = models.ForeignKey(
        'authentication.Student',
        on_delete=models.CASCADE,
        related_name='club_attendances',
    )
    date = models.DateField()
    status = models.CharField(choices=ATTENDANCE_CHOICES, max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'session_id', 'student_id']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'student', 'date'],
                condition=models.Q(is_deleted=False),
                name='unique_active_club_attendance',
            ),
        ]

    def __str__(self):
        return f"{self.session.club.name}: {self.student} on {self.date} ({self.status})"
