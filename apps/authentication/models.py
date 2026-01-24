from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from core import settings


MAX_AVATAR_SIZE_MB = 5
MAX_AVATAR_SIZE_BYTES = MAX_AVATAR_SIZE_MB * 1024 * 1024


def validate_avatar_size(file):
    """Validate that avatar file size doesn't exceed the maximum allowed size."""
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


class SchoolGroup(models.Model):
    name = models.CharField(max_length=100)
    avatar = models.FileField(upload_to='school_group/', blank=True, null=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    ROLE_PARENT = 'parent'
    ROLE_TEACHER = 'teacher'
    HOMEROOM_TEACHER= 'homeroom_teacher'
    ROLE_STUDENT = 'student'
    ROLE_SUPERVISOR = 'supervisor'
    ROLE_CLASS_TEACHER = 'class_teacher'
    ROLE_PRINCIPAL = 'principal'
    ROLE_ADMIN = 'admin'

    ROLE_CHOICES = [
        (ROLE_PARENT, 'Parent'),
        (ROLE_TEACHER, 'Teacher'),
        (HOMEROOM_TEACHER, 'Homeroom Teacher'),
        (ROLE_STUDENT, 'Student'),
        (ROLE_SUPERVISOR, 'Supervisor'),
        (ROLE_PRINCIPAL, 'Principal'),
        (ROLE_ADMIN, 'Admin'),
    ]

    SCHOOL_CHOICES = [
        ('muzafar_alimbayev', 'Muzafar Alimbayev 21'),
        ('bukhar_zhyrau', 'Bukhar Zhyrau 19/1'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    avatar = models.FileField(
        upload_to='avatars/%Y/%m/%d/',
        default='avatars/default/default-user.jpeg',
        validators=[validate_avatar_size]
    )
    school = models.CharField(max_length=20, choices=SCHOOL_CHOICES, default='muzafar_alimbayev')

    def __str__(self):
        return self.first_name + " " + self.last_name

    def _has_group(self, group_name):
        """Check if user belongs to a specific group."""
        return self.groups.filter(name=group_name).exists()

    def is_teacher(self):
        """Check if user is a teacher (includes homeroom teachers)."""
        if self._has_group('Teacher') or self._has_group('HomeroomTeacher'):
            return True
        return self.role in (self.ROLE_TEACHER, self.HOMEROOM_TEACHER)

    def is_homeroom_teacher(self):
        """Check if user is specifically a homeroom teacher."""
        if self._has_group('HomeroomTeacher'):
            return True
        return self.role == self.HOMEROOM_TEACHER

    def is_admin(self):
        """Check if user is an admin."""
        return self._has_group('Admin') or self.role == self.ROLE_ADMIN

    def is_manager(self):
        """Check if user is a supervisor/manager."""
        return self._has_group('Supervisor') or self.role == self.ROLE_SUPERVISOR

    def is_principal(self):
        """Check if user is a principal."""
        return self._has_group('Principal') or self.role == self.ROLE_PRINCIPAL

    def is_parent(self):
        """Check if user is a parent."""
        return self._has_group('Parent') or self.role == self.ROLE_PARENT

    def is_student(self):
        """Check if user is a student."""
        return self._has_group('Student') or self.role == self.ROLE_STUDENT

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



class Student(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    classroom = models.ForeignKey(
        'home.ClassRoom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    subjects = models.ManyToManyField(
        'home.Subject',
        blank=True,
        related_name="students"
    )
    school_group = models.ForeignKey(SchoolGroup, on_delete=models.SET_NULL, null=True)
    academic_year = models.ForeignKey(
        'home.AcademicYear',
        related_name='students',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text='Enrollment year for this student'
    )


@receiver(pre_save, sender=Student)
def assign_academic_year_for_student(sender, instance: 'Student', **kwargs):
    """Auto-assign student's academic year before save.

    Priority:
    1) If student has a classroom with an academic_year, use it
    2) Otherwise, default to the latest AcademicYear (by year desc) if available
    """
    if instance.academic_year_id:
        return

    try:
        classroom = instance.classroom
        if classroom and getattr(classroom, 'academic_year_id', None):
            instance.academic_year_id = classroom.academic_year_id
            return

        # Fallback: latest academic year
        from apps.home.models import AcademicYear  # local import to avoid circular deps
        latest_year = AcademicYear.objects.order_by('-year').first()
        if latest_year:
            instance.academic_year = latest_year
    except Exception:
        # Do not block save on any failure here
        pass


class Parent(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    students = models.ManyToManyField(Student, blank=True, related_name="parent")


class Teacher(models.Model):
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
    classroom = models.ForeignKey(
        'home.ClassRoom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        full_name = self.user.get_full_name()
        return full_name if full_name.strip() else self.user.username


class Supervisor(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)


class PsychologicalState(models.Model):
    name = models.CharField(max_length=100)
    comment = models.TextField(blank=True, null=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True)

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
    name = models.CharField(max_length=100, unique=True)
    comment = models.TextField(blank=True, null=True)

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
        raw_password = getattr(instance, '_raw_password', None)

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

        from apps.notification.models import Notification, RegisterNotify
        notification = Notification.objects.create(user=instance, action='register')
        RegisterNotify.objects.create(notification=notification)

