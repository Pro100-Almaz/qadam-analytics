from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import CustomUser, SchoolGroup, Teacher
from ..home.models import ClassRoom


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Username",
                "class": "form-control"
            }
        ))
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Password",
                "class": "form-control"
            }
        ))

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['username','email',
                  'first_name', 'last_name',
                  'address', 'phone_number', 'date_of_birth']
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control"
            }
        )
    )
    email = forms.CharField(
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control"
            }
        )
    )
    first_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control"
            }
        )
    )
    last_name = forms.CharField(
        required=False,
        widget = forms.TextInput(
            attrs = {
                "class" : "form-control"
            }
        )
    )
    phone_number = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "multisteps-form__input form-control",
                "type": "number",
                "pattern": r"\d*",
                "inputmode": "numeric"
            }
        )
    )
    address = forms.CharField(
        required = False,
        widget=forms.TextInput(
            attrs = {
                "class" : "form-control"
            }
        )
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "date"
            }
        )
    )


class SignUpForm(UserCreationForm):
    first_name = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Например, Азамат",
                "class": "multisteps-form__input form-control"
            }
        )
    )
    last_name = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Например, Ибрагимов",
                "class": "multisteps-form__input form-control"
            }
        )
    )
    school = forms.ChoiceField(
        required=False,
        choices = CustomUser.SCHOOL_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-control"
            }
        )
    )
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "placeholder": "eg. argon@dashboard.com",
                "class": "multisteps-form__input form-control"
            }
        ))
    password1 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "******",
                "class": "multisteps-form__input form-control"
            }
        ))
    password2 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "******",
                "class": "multisteps-form__input form-control"
            }
        ))
    address = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Например, Бухар жырау 40",
                "class": "multisteps-form__input form-control"
            }
        )
    )
    role = forms.ChoiceField(
        choices = CustomUser.ROLE_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-control"
            }
        )
    )
    phone_number = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "+7 (___) ___ ____",
                "class": "multisteps-form__input form-control",
                "type": "number",
                "pattern": r"\d*",
                "inputmode": "numeric"
            }
        )
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "date"
            }
        )
    )
    avatar = forms.ImageField(
        required=False,
        widget=forms.FileInput(
            attrs={
                "class": "form-control",
                "accept": "image/*"
            }
        )
    )
    occupation = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Преподаваемый предмет",
            "class": "form-control",
            "id": "id_occupation"
        })
    )
    classroom = forms.ModelChoiceField(
        queryset=ClassRoom.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control",
            "id": "id_classroom"
        })
    )
    employment_type = forms.ChoiceField(
        choices = Teacher.EMPLOYMENT_TYPE_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-control"
            }
        )
    )
    gender = forms.ChoiceField(
        choices=Teacher.GENDER_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-control"
            }
        )
    )
    academic_degree = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Например: Бакалавр Компьютерных Наук",
            "class": "form-control",
            "id": "id_occupation"
        })
    )
    student_id = forms.IntegerField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "ID ученика",
            "class": "form-control",
            "id": "id_student_id"
        })
    )
    school_group = forms.ModelChoiceField(
        queryset=SchoolGroup.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control",
            "id": "id_school_group"
        })
    )


    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'school', 'email', 'password1', 'password2', 'address', 'role', 'phone_number', 'date_of_birth', 'avatar')

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data['role']
        if commit:
            user.save()

            if role == 'teacher':
                from .models import Teacher
                Teacher.objects.create(user=user, occupation=self.cleaned_data.get('occupation'))
            elif role == 'student':
                from .models import Student
                Student.objects.create(user=user, classroom=self.cleaned_data.get('classroom'), school_group=self.cleaned_data.get('school_group'))
            elif role == 'parent':
                from .models import Parent
                student_id = self.cleaned_data.get('student_id')
                Parent.objects.create(user=user, student_id=student_id)
        return user

class ForgetPasswordForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "placeholder": "Почта или Логин",
                "class": "form-control"
            }
        ))


class VerificationPasswordForm(forms.Form):
    verification_code = forms.IntegerField(
        min_value=100000,
        max_value=999999,
        widget=forms.NumberInput(attrs={
            "placeholder": "Код подтверждения",
            "class": "form-control",

        })
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Новый пароль",
            "class": "form-control"
        })
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Повторите пароль",
            "class": "form-control"
        })
    )
    actual_code = forms.CharField(widget=forms.HiddenInput)


    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'school', 'email', 'password1', 'password2', 'address', 'role', 'phone_number', 'date_of_birth', 'avatar')



