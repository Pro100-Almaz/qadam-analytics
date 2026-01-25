from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import CustomUser, SchoolGroup, Teacher, MAX_AVATAR_SIZE_MB, MAX_AVATAR_SIZE_BYTES
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
        choices=CustomUser.GROUP_CHOICES,
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
        fields = ('first_name', 'last_name', 'school', 'email', 'password1', 'password2', 'address', 'phone_number', 'date_of_birth', 'avatar')

    def clean_avatar(self):
        """Validate avatar file size."""
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'size'):
            if avatar.size > MAX_AVATAR_SIZE_BYTES:
                raise forms.ValidationError(
                    f'Avatar file size must be less than {MAX_AVATAR_SIZE_MB}MB. '
                    f'Current size: {avatar.size / (1024 * 1024):.2f}MB'
                )
        return avatar

    def save(self, commit=True):
        user = super().save(commit=False)
        group_name = self.cleaned_data['role']  # This now contains Group name directly
        if commit:
            user.save()
            self._assign_group(user, group_name)

            # Handle avatar upload explicitly
            avatar = self.cleaned_data.get('avatar')
            if avatar:
                user.avatar = avatar
                user.save(update_fields=['avatar'])

            # Create role-specific profile based on selected group
            if group_name in (CustomUser.GROUP_TEACHER, CustomUser.GROUP_HOMEROOM_TEACHER):
                from .models import Teacher
                Teacher.objects.create(
                    user=user,
                    occupation=self.cleaned_data.get('occupation'),
                    gender=self.cleaned_data.get('gender'),
                    academic_degree=self.cleaned_data.get('academic_degree'),
                    employment_type=self.cleaned_data.get('employment_type'),
                    classroom=self.cleaned_data.get('classroom'),
                )
            elif group_name == CustomUser.GROUP_STUDENT:
                from .models import Student
                Student.objects.create(
                    user=user,
                    classroom=self.cleaned_data.get('classroom'),
                    school_group=self.cleaned_data.get('school_group'),
                )
            elif group_name == CustomUser.GROUP_PARENT:
                from .models import Parent, Student
                parent = Parent.objects.create(user=user)
                # Link to student if student_id provided (ManyToMany relationship)
                student_id = self.cleaned_data.get('student_id')
                if student_id:
                    try:
                        student = Student.objects.get(pk=student_id)
                        parent.students.add(student)
                    except Student.DoesNotExist:
                        pass
            elif group_name in (CustomUser.GROUP_SUPERVISOR, CustomUser.GROUP_PRINCIPAL):
                from .models import Supervisor
                Supervisor.objects.create(user=user)
            # Admin group doesn't need a profile model
        return user

    def _assign_group(self, user, group_name):
        """Assign the user to the specified Django Group."""
        from django.contrib.auth.models import Group
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

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


class ResetPasswordForm(forms.Form):
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Новый Пароль",
            "class": "form-control"
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Повторите Пароль",
            "class": "form-control"
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password:
            if new_password != confirm_password:
                raise forms.ValidationError("Пароли не совпадают")
        return cleaned_data
