# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import CustomUser


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
                "pattern": "\d*",
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

    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'school', 'email', 'password1', 'password2', 'address', 'role', 'phone_number', 'date_of_birth')
