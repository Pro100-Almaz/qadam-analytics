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
from errors import find_error_by_key
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

def register_user(request):
    form = SignUpForm()
    context = {"form": form}

    if request.method == "POST":
        avatar_file = request.FILES.get('avatar')
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)

            user.avatar = avatar_file
            user.username = user.email
            if CustomUser.objects.filter(username=user.username).exists():
                context["error"] = find_error_by_key("email")
            else:
                user.save()
                login(request, user)
                return redirect("/")

    for error in form.errors.keys():
        error_text = find_error_by_key(error)
        context["error"] = error_text
        break

    return render(request, "accounts/register.html", context)


@login_required
def custom_logout_view(request):
    logout(request)

    return redirect('/login/')
