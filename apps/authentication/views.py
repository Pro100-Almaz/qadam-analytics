# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

# Create your views here.
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

from .forms import LoginForm, SignUpForm
from .models import CustomUser
from django.forms.utils import ErrorList


def login_view(request):
    form = LoginForm(request.POST or None)

    msg = None

    if request.method == "POST":

        if form.is_valid():
            username = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect("/")
            else:
                msg = 'Invalid credentials'
        else:
            msg = 'Error validating the form'

    return render(request, "accounts/login.html", {"form": form, "msg": msg})

REGISTER_USER_ERRORS = {"password1": "Пароль слишком простой", "password2": "Пароли не совпадают", "email": "Адрес электронной почты уже зарегистрирован"}
def register_user(request):
    form = SignUpForm()

    if request.method == "POST":
        avatar_file = request.FILES.get('avatar')
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)

            user.avatar = avatar_file
            user.username = user.email
            if CustomUser.objects.filter(username=user.username).exists():
                form.add_error('email', "Адрес электронной почты уже зарегистрирован")
            else:
                user.save()
                login(request, user)
                return redirect("/")
    for error in form.errors.keys():
        print(form.errors[error])
        form.errors[error] = ErrorList([REGISTER_USER_ERRORS[error]])
        print(error)
    return render(request, "accounts/register.html", {"form": form})


@login_required
def custom_logout_view(request):
    logout(request)

    return redirect('/login/')
