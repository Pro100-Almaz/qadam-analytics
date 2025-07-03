from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractUser
from django.core.mail import send_mail
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from core import settings


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

    def is_student(self):
        return self.role == CustomUser.ROLE_STUDENT

    def get_student_id(self):
        if self.is_parent():
            try:
                parent = Parent.objects.get(user=self)
                return parent.student_id
            except Parent.DoesNotExist:
                return None
        return None

    def get_linked_student(self):
        student_id = self.get_student_id()
        if student_id:
            try:
                student = CustomUser.objects.get(student_id=student_id)
                return Student.objects.get(user=student)
            except (Student.DoesNotExist, CustomUser.DoesNotExist):
                return None
        return None



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

    classroom = models.ForeignKey(
        'home.ClassRoom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )


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


@receiver(post_save, sender=CustomUser)
def registration_email_post_send(sender, instance, created, *args, **kwargs):
    if created:
        raw_password = "Qadam!123_" + instance.first_name + "!" + instance.last_name
        instance.password = make_password(raw_password)
        CustomUser.objects.filter(pk=instance.pk).update(password=instance.password)
        print(instance.username, raw_password, instance.password)

        subject = 'Уведомление о учетной записи Qadam Analytics'
        html_message = render_to_string("email/registration_login_pw_email.html",
                                   {"user": instance, "password": raw_password})

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
