from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def user_avatar_upload_path():
    pass


class SchoolGroup(models.Model):
    name = models.CharField(max_length=100)
    avatar = models.FileField(upload_to='school_group/', blank=True, null=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    ROLE_PARENT = 'parent'
    ROLE_TEACHER = 'teacher'
    ROLE_STUDENT = 'student'
    ROLE_SUPERVISOR = 'supervisor'
    ROLE_CLASS_TEACHER = 'class_teacher'
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
    avatar = models.FileField(
        upload_to='avatars/%Y/%m/%d/',
        default='avatars/default/default-user.jpeg'
    )
    school = models.CharField(max_length=20, choices=SCHOOL_CHOICES, default='muzafar_alimbayev')

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


class Student(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    classroom = models.ForeignKey(
        'home.ClassRoom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    school_group = models.ForeignKey(SchoolGroup, on_delete=models.SET_NULL, null=True)


class Parent(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    student_id = models.IntegerField(blank=True, null=True)


class Teacher(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    occupation = models.CharField(max_length=50, blank=True, null=True)


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

    def __str__(self):
        return self.name


class PsychologicalStateTemplates(models.Model):
    name = models.CharField(max_length=100, unique=True)
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name
