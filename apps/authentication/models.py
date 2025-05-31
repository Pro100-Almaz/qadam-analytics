import os
import hashlib

from django.contrib.auth.models import AbstractUser
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

