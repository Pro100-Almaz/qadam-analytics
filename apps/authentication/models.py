import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from simple_history.models import HistoricalRecords

from core.models import SchoolConsistentModel, SchoolDerivedMixin
from core.tenancy import SchoolScopedManager
from core.validators import is_stored_file
from core import settings


MAX_AVATAR_SIZE_MB = 5
MAX_AVATAR_SIZE_BYTES = MAX_AVATAR_SIZE_MB * 1024 * 1024


def validate_avatar_size(file):
    """Validate that an avatar *upload* does not exceed the maximum size.

    Skips a file that is already in storage: reading its size is a HeadObject
    against S3, and a missing object made every save of that row a 500. See
    `core.validators.is_stored_file`.
    """
    if is_stored_file(file):
        return
    if file.size > MAX_AVATAR_SIZE_BYTES:
        raise ValidationError(
            f'Avatar file size must be less than {MAX_AVATAR_SIZE_MB}MB. '
            f'Current size: {file.size / (1024 * 1024):.2f}MB'
        )


def user_avatar_upload_path(instance, filename):
    """Legacy upload path function - kept for migration compatibility.
    Current avatar field uses 'avatars/%Y/%m/%d/' string path instead.
    """
    return f'avatars/{filename}'


class SchoolVisibleManager(models.Manager):
    """Schools an API may list. NOT a substitute for an authorization check.

    This expresses one half of "visible": the school is live. It cannot express
    the other half — visible *to whom* — because a manager has no user. For any
    non-superuser the only school they may see is their own, and since
    `School.objects` is unscoped by design, an endpoint that lists this
    queryset without also narrowing by the requesting user lets anyone
    enumerate every tenant. Narrow it in the view.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class School(models.Model):
    """A tenant. Every school-owned row reaches exactly one of these.

    Not to be confused with SchoolGroup below, which is an Orda house
    (Aq Orda, Uly Orda, ...) — a cohort *inside* a school, not a school.
    """

    #: Declared first and explicitly, because Django takes the FIRST manager as
    #: the default and the default is what forward FKs, the admin and
    #: migrations resolve through. Leaving it implicit would make `visible`
    #: below the default and silently hide deactivated schools from all of
    #: them. It is a plain Manager: the tenant root cannot be scoped by itself.
    objects = models.Manager()
    #: For API listings only — see SchoolVisibleManager.
    visible = SchoolVisibleManager()

    uuid = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True,
        help_text="Public identifier — this is what crosses the network, never the pk.",
    )
    slug = models.SlugField(
        max_length=50, unique=True,
        help_text="Stable internal key used by migrations and script --school flags.",
    )
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50, blank=True, default='')

    address = models.TextField(blank=True, default='')
    contact_phone = models.CharField(max_length=20, blank=True, default='')
    contact_email = models.EmailField(blank=True, default='')

    timezone = models.CharField(max_length=64, default='Asia/Almaty')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Школа'
        verbose_name_plural = 'Школы'

    def __str__(self):
        return self.name


class SchoolGroup(models.Model):
    SCHOOL_PATH = 'school'
    objects = SchoolScopedManager()

    name = models.CharField(max_length=100)
    avatar = models.FileField(upload_to='school_group/', blank=True, null=True)
    color = models.CharField(max_length=7, blank=True, default='')
    # Root: an Orda house belongs to exactly one school.
    school = models.ForeignKey(
        'authentication.School', related_name='school_groups',
        on_delete=models.PROTECT,
    )

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    SCHOOL_PATH = 'school'

    #: Identity lookups must be global, so the DEFAULT manager is unscoped.
    #: `ModelBackend.authenticate` calls `_default_manager.get_by_natural_key()`
    #: before anyone knows who the user is — a fail-closed default manager makes
    #: login itself raise. Same for JWTAuthentication.get_user, PasswordResetForm,
    #: createsuperuser and the admin login. Person-level isolation is enforced
    #: through the five profile models instead, each SCHOOL_PATH='user__school',
    #: which is what the API actually lists.
    objects = UserManager()
    #: Scoped, for listings, pickers and the admin.
    in_school = SchoolScopedManager()

    # Group name constants (used for consistency across the codebase)
    GROUP_PARENT = 'Parent'
    GROUP_TEACHER = 'Teacher'
    GROUP_HOMEROOM_TEACHER = 'HomeroomTeacher'
    GROUP_STUDENT = 'Student'
    GROUP_SUPERVISOR = 'Supervisor'
    GROUP_PRINCIPAL = 'Principal'
    GROUP_ADMIN = 'Admin'
    GROUP_PSYCHOLOGIST = 'Psychologist'
    GROUP_CLUB_MANAGER = 'ClubManager'

    # Choices for forms - maps internal group name to display name
    GROUP_CHOICES = [
        (GROUP_PARENT, 'Parent'),
        (GROUP_TEACHER, 'Teacher'),
        (GROUP_HOMEROOM_TEACHER, 'Homeroom Teacher'),
        (GROUP_STUDENT, 'Student'),
        (GROUP_SUPERVISOR, 'Supervisor'),
        (GROUP_PRINCIPAL, 'Principal'),
        (GROUP_ADMIN, 'Admin'),
        (GROUP_PSYCHOLOGIST, 'Psychologist'),
        (GROUP_CLUB_MANAGER, 'Club Manager'),
    ]

    # Display names for groups
    GROUP_DISPLAY_NAMES = {
        GROUP_PARENT: 'Parent',
        GROUP_TEACHER: 'Teacher',
        GROUP_HOMEROOM_TEACHER: 'Homeroom Teacher',
        GROUP_STUDENT: 'Student',
        GROUP_SUPERVISOR: 'Supervisor',
        GROUP_PRINCIPAL: 'Principal',
        GROUP_ADMIN: 'Admin',
        GROUP_PSYCHOLOGIST: 'Psychologist',
        GROUP_CLUB_MANAGER: 'Club Manager',
    }

    phone_number = models.CharField(max_length=20, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    avatar = models.FileField(
        upload_to='avatars/%Y/%m/%d/',
        default='avatars/default/default-user.jpeg',
        validators=[validate_avatar_size]
    )
    # Legacy free-text school label, superseded by the `school` FK below.
    #
    # KEPT PERMANENTLY — do not add a RemoveField for this. It is the input the
    # phase-1 backfill read to decide each user's tenant (authentication/0038),
    # and therefore the only independent record of that decision. If a user
    # turns out to be in the wrong school, this column is what a manual
    # recovery reads to put them back. Retention was an explicit condition of
    # approving the tenant split; an earlier draft of the plan dropped it in
    # phase 7, and that instruction has been reversed.
    #
    # `editable=False` and written by nothing, so it cannot drift. Do not read
    # it at runtime either — `school` is the live field.
    #
    # Phase 7 dropped two things from it. `choices` named exactly the two
    # hardcoded schools the whole plan exists to generalise away from, and a
    # third tenant would have made this column invalid for its users while
    # meaning nothing to them. The `'muzafar_alimbayev'` default was worse: it
    # wrote school #1's name onto every user created *after* the split,
    # including school #2's, filling the one column kept as the recovery record
    # with an assertion nobody had made. Blank is the honest value — this user
    # predates nothing.
    legacy_school = models.CharField(
        max_length=20, blank=True, default='', editable=False,
    )
    school = models.ForeignKey(
        'authentication.School',
        related_name='users',
        on_delete=models.PROTECT,
        null=True, blank=True,
        help_text="The tenant this user belongs to. Exactly one, except superusers.",
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            # Every user belongs to exactly one school. Superusers are the sole
            # exception — they span all schools, and `createsuperuser` has no way
            # to supply one, so NULL is permitted only for them.
            models.CheckConstraint(
                condition=models.Q(school__isnull=False) | models.Q(is_superuser=True),
                name='user_has_school_unless_superuser',
            ),
        ]

    def __str__(self):
        return self.first_name + " " + self.last_name

    def _has_group(self, group_name):
        """Check if user belongs to a specific group."""
        return self.groups.filter(name=group_name).exists()

    @property
    def primary_group(self):
        """Get the user's primary group (first group found)."""
        priority = ["Admin", "HomeroomTeacher"]
        _groups = self.groups.all()
        for p in priority:
            if any(g.name == p for g in _groups):
                return p
        return _groups.first().name if _groups else None

    @property
    def role(self):
        """Backwards-compatible property that returns the primary group name in lowercase."""
        group = self.primary_group
        if group:
            # Convert group name to lowercase role format for backwards compatibility
            return group.lower().replace('homeroomteacher', 'homeroom_teacher')
        return None

    def get_role_display(self):
        """Get human-readable display name for user's primary role/group."""
        group = self.primary_group
        if group:
            return self.GROUP_DISPLAY_NAMES.get(group, group)
        return 'No Role'

    def get_all_roles_display(self):
        """Get display names for all user's groups."""
        return [self.GROUP_DISPLAY_NAMES.get(g.name, g.name) for g in self.groups.all()]

    def is_teacher(self):
        """Check if user is a teacher (includes homeroom teachers)."""
        return self._has_group(self.GROUP_TEACHER) or self._has_group(self.GROUP_HOMEROOM_TEACHER)

    def is_homeroom_teacher(self):
        """Check if user is specifically a homeroom teacher."""
        return self._has_group(self.GROUP_HOMEROOM_TEACHER)

    def is_admin(self):
        """Check if user is an admin."""
        return self._has_group(self.GROUP_ADMIN)

    def is_manager(self):
        """Check if user is a supervisor/manager."""
        return self._has_group(self.GROUP_SUPERVISOR)

    def is_principal(self):
        """Check if user is a principal."""
        return self._has_group(self.GROUP_PRINCIPAL)

    def is_parent(self):
        """Check if user is a parent."""
        return self._has_group(self.GROUP_PARENT)

    def is_psychologist(self):
        """Check if user is a psychologist."""
        return self._has_group(self.GROUP_PSYCHOLOGIST)

    def is_student(self):
        """Check if user is a student."""
        return self._has_group(self.GROUP_STUDENT)

    def is_club_manager(self):
        """Check if user is a club manager."""
        return self._has_group(self.GROUP_CLUB_MANAGER)

    def get_students(self):
        """Get all students linked to this parent user."""
        if self.is_parent():
            try:
                parent = Parent.objects.prefetch_related('students').get(user=self)
                return parent.students.all()
            except Parent.DoesNotExist:
                return None
        return None

    def get_first_student(self):
        """Get the first student linked to this parent (for backwards compatibility)."""
        students = self.get_students()
        if students:
            return students.first()
        return None



class Student(SchoolConsistentModel):
    SCHOOL_PATH = 'user__school'
    objects = SchoolScopedManager()
    #: `user` is the student's own school, so this reads as: an Orda house
    #: from a school the student does not attend is a cross-tenant write, not
    #: a stray FK. `intake_year` is absent because it is no longer a relation —
    #: see the field below.
    SCHOOL_CONSISTENT_FIELDS = ('user', 'school_group')

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    subjects = models.ManyToManyField(
        'home.Subject',
        blank=True,
        related_name="students"
    )
    school_group = models.ForeignKey(SchoolGroup, on_delete=models.SET_NULL, null=True, blank=True)
    #: The year this student first appeared, as a label: "2025/2026".
    #:
    #: It was a FK to AcademicYear, and that was wrong in three ways. It read
    #: as the student's *current* year but was assigned once at creation and
    #: never advanced — `rollover_academic_year` writes class groups and
    #: enrollments, never this — so after one rollover it named a past year
    #: while the student was enrolled in the present one. The real year-by-year
    #: record is Enrollment -> ClassGroup -> AcademicYear, which is multi-year
    #: and which a single FK could never express anyway. And because years are
    #: per-school since §1b, the FK made this a tenancy-coupled field: it had
    #: to be re-pointed whenever a student changed school, or their profile
    #: failed its own consistency check.
    #:
    #: As a plain string it is what it always meant — when this student entered
    #: — and it survives a school move untouched, needs no re-pointing, and is
    #: out of SCHOOL_CONSISTENT_FIELDS entirely. Nothing used the reverse
    #: relation `AcademicYear.students`, so the FK bought nothing it cost.
    intake_year = models.CharField(
        max_length=40, blank=True, default='',
        help_text='Academic year this student entered, e.g. "2025/2026". '
                  'Set once on creation; history, not a live pointer.',
    )
    medical_features = models.TextField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    def get_admin_label(self):
        from apps.home.models import ClassGroup
        name = str(self)
        enrollment = self.enrollments.filter(
            status='active', class_group__category=ClassGroup.MAJOR_CHOICE
        ).first()
        if enrollment and enrollment.class_group:
            return f'{name} ({enrollment.class_group.grade_level}{enrollment.class_group.letter})'
        return name

    def get_current_enrollment(self):
        """Get current active enrollment in a major class group."""
        from apps.home.models import Enrollment
        return Enrollment.get_current_enrollment(self)

    def get_current_minor_enrollments(self):
        """Get current active enrollments in minor class groups."""
        from apps.home.models import Enrollment
        return Enrollment.get_current_minor_enrollments(self)

    def get_current_class_group(self):
        """Get the major class group from current enrollment."""
        enrollment = self.get_current_enrollment()
        return enrollment.class_group if enrollment else None

    def get_current_minor_class_groups(self):
        """Get the minor class groups the student is currently enrolled in."""
        return [e.class_group for e in self.get_current_minor_enrollments()]

    def get_enrollment_history(self):
        """Get all enrollments ordered by year."""
        return self.enrollments.select_related(
            'class_group', 'class_group__grade_level', 'class_group__academic_year'
        ).order_by('-class_group__academic_year__year')

    def enroll_in_class(self, class_group, academic_year, start_date=None):
        """Enroll student in a class group."""
        from apps.home.models import Enrollment
        return Enrollment.enroll_student(self, class_group, academic_year, start_date)


@receiver(pre_save, sender=Student)
def assign_intake_year_for_student(sender, instance: 'Student', **kwargs):
    """Stamp the student's school's active year on creation, and never again.

    "The active year" is only meaningful next to a school — years are
    per-school since §1b — and the right school here is the **student's own**,
    read off `user.school`, not whatever scope the caller happens to be in.
    Those are normally the same; when they are not, the student's own school is
    the one that cannot be wrong.

    That is also why this reads `_base_manager` rather than the scoped
    `objects`: the school is already named in the filter, so narrowing it a
    second time by the ambient scope could only ever subtract. It behaves
    identically in a request, a script, the shell and a Celery worker.

    Only the year *string* is kept. The row it came from belongs to one school
    and will be superseded at the next rollover; the label will still be true
    in ten years, which is the whole point of the field.

    The blanket `except Exception: pass` this replaced was the worst failure
    mode the tenancy design can produce. It fired on every Student save, and
    under fail-closed scoping it would have swallowed SchoolScopeError and
    written an empty year silently, with no log line — inverting the
    fail-closed guarantee into a quiet data defect. There is deliberately no
    handler here.
    """
    if instance.intake_year:
        return

    from apps.home.models import AcademicYear

    school_id = instance.user.school_id if instance.user_id else None
    if school_id is None:
        # A student with no school cannot have a year picked for them. The
        # `user_has_school_unless_superuser` constraint means this is not a
        # state a real student reaches.
        return

    years = AcademicYear._base_manager.filter(school_id=school_id)
    year = (
        years.filter(is_active=True).first()
        or years.order_by('-year').first()
    )
    if year is not None:
        instance.intake_year = year.year


class Parent(models.Model):
    SCHOOL_PATH = 'user__school'
    objects = SchoolScopedManager()

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    students = models.ManyToManyField(Student, blank=True, related_name="parent")


class Teacher(models.Model):
    SCHOOL_PATH = 'user__school'
    objects = SchoolScopedManager()

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    #identification
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True, null=True)
    #professional
    academic_degree = models.CharField(max_length=50, blank=True, null=True)

    EMPLOYMENT_TYPE_CHOICES = [
        ('full_time', 'Full-Time'),
        ('part_time', 'Part-Time'),
    ]
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, blank=True, null=True)

    subjects = models.ManyToManyField('home.Subject', related_name='assigned_teachers', blank=True)

    #working place
    occupation = models.CharField(max_length=50, blank=True, null=True)
    working_hours = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        full_name = self.user.get_full_name()
        return full_name if full_name.strip() else self.user.username


class Supervisor(models.Model):
    SCHOOL_PATH = 'user__school'
    objects = SchoolScopedManager()

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)


class ClubManager(models.Model):
    SCHOOL_PATH = 'user__school'
    objects = SchoolScopedManager()

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)


class PsychologicalState(SchoolDerivedMixin, models.Model):
    """A psychologist's note about a student.

    `student` is nullable, so the row carries its own school rather than
    reaching one by join. Neither source below is guaranteed: a note with no
    student has no student to ask, and `added_by` is a superuser's row with no
    school of its own. Every live creation site passes a student, so the caller
    must supply `school` explicitly for the school-wide case — which
    SchoolDerivedMixin.save() now says in as many words instead of raising a
    bare NOT NULL IntegrityError.
    """

    SCHOOL_PATH = 'school'
    SCHOOL_DERIVED_FROM = ('student__user', 'added_by')
    #: One field, and still worth declaring: it is the column-vs-parent
    #: check that stops a sensitive record being filed under the wrong
    #: tenant, which here is a disclosure rather than a misfile.
    SCHOOL_CONSISTENT_FIELDS = ('student',)
    objects = SchoolScopedManager()

    name = models.CharField(max_length=100)
    comment = models.TextField(blank=True, null=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True)
    school = models.ForeignKey(
        'authentication.School', related_name='psychological_states',
        on_delete=models.PROTECT,
    )

    score = models.PositiveIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5)
        ],
        help_text="На сколько звезд оцениваете состояние ученика?"
    )

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_psychological_states'
    )
    time_added = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        return self.name


class PsychologicalStateTemplates(models.Model):
    SCHOOL_PATH = 'school'
    objects = SchoolScopedManager()

    name = models.CharField(max_length=100)
    comment = models.TextField(blank=True, null=True)
    # Root: templates are per-school.
    school = models.ForeignKey(
        'authentication.School', related_name='psychological_state_templates',
        on_delete=models.PROTECT,
    )

    class Meta:
        constraints = [
            # §7, and the one constraint tenancy actually *requires*: `name`
            # was globally unique, so school #2 could never create a template
            # whose name school #1 had already taken — a tenant blocking a
            # tenant it cannot see. Relaxing a unique constraint can never
            # fail on existing data.
            models.UniqueConstraint(
                fields=['school', 'name'],
                name='psychstatetemplate_unique_name_per_school',
            ),
        ]

    def __str__(self):
        return self.name


@receiver(pre_save, sender=CustomUser)
def delete_old_avatar_on_change(sender, instance, **kwargs):
    """Delete old avatar file when user uploads a new one to prevent orphaned files."""
    if not instance.pk:
        return  # New user, no old avatar to delete

    try:
        old_instance = CustomUser.objects.get(pk=instance.pk)
    except CustomUser.DoesNotExist:
        return

    old_avatar = old_instance.avatar
    new_avatar = instance.avatar

    # Check if avatar has changed and old one isn't the default
    if old_avatar and old_avatar != new_avatar:
        default_avatar = 'avatars/default/default-user.jpeg'
        if old_avatar.name != default_avatar:
            # Delete the old file from storage
            old_avatar.delete(save=False)


@receiver(post_save, sender=CustomUser)
def registration_email_post_send(sender, instance, created, *args, **kwargs):
    if settings.DEBUG:
        return

    if created:
        subject = 'Уведомление о учетной записи Qadam Analytics'
        html_message = render_to_string("email/registration_login_pw_email.html",
                                   {"user": instance, "password": "[скрыто в целях защиты ваших данных]"})
        plain_message = strip_tags(html_message)
        from_mail = settings.DEFAULT_FROM_EMAIL
        to_mail = [instance.email]

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=from_mail,
            recipient_list=to_mail,
            html_message=html_message
        )

        from apps.notification.models import Notification
        Notification.objects.create(
            user=instance,
            type=Notification.NotificationType.REGISTER,
            title='Registration',
            message='User registered successfully',
        )
