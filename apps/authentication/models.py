import os
import hashlib

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from apps.home.models import ClassRoom


def user_avatar_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    salt = os.urandom(16)

    encoded_str = salt + instance.email.encode('utf-8')
    hash_object = hashlib.sha256(encoded_str)
    hex_digest = hash_object.hexdigest()

    filename = f"avatar_{hex_digest}.{ext}"
    return os.path.join('user_avatars', str(instance.email), filename)


class SchoolGroup(models.Model):
    name = models.CharField(max_length=100)
    avatar = models.FileField(upload_to='school_group/', blank=True, null=True)

    def __str__(self):
        return self.name


class PsychologicalState(models.Model):
    name = models.CharField(max_length=100)
    comment = models.TextField(blank=True, null=True)

    score = models.PositiveIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5)
        ],
        help_text="На сколько звезд оцениваете состояние ученика?"
    )

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    ROLE_PARENT = 'parent'
    ROLE_TEACHER = 'teacher'
    ROLE_STUDENT = 'student'
    ROLE_SUPERVISOR = 'supervisor'
    ROLE_PRINCIPAL = 'principal'
    ROLE_ADMIN = 'admin'

    ROLE_CHOICES = [
        (ROLE_PARENT, 'Parent'),
        (ROLE_TEACHER, 'Teacher'),
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
    avatar = models.FileField(upload_to='avatars/%Y/%m/%d/', blank=True, null=True)
    school = models.CharField(max_length=20, choices=SCHOOL_CHOICES, default='muzafar_alimbayev')
    occupation = models.CharField(max_length=50, blank=True, null=True)
    student_id = models.IntegerField(blank=True, null=True)
    school_group = models.ForeignKey(SchoolGroup, on_delete=models.SET_NULL, null=True)
    physical_state = models.ForeignKey(PsychologicalState, on_delete=models.SET_NULL, null=True)

    classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )


    def __str__(self):
        return self.first_name + " " + self.last_name

    def is_teacher(self):
        return self.role == CustomUser.ROLE_TEACHER

    def is_manager(self):
        return self.role == CustomUser.ROLE_SUPERVISOR

    def is_principal(self):
        return self.role == CustomUser.ROLE_PRINCIPAL

    def is_parent(self):
        return self.role == CustomUser.ROLE_PARENT

    def get_student_id(self):
        return self.student_id


