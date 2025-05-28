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


def login_view(request):
    form = LoginForm(request.POST or None)

    msg = None
    context = {"form": form}

    if request.method == "POST":

        if form.is_valid():
            username = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(username=username, password=password)
            if user:
                login(request, user)
                return redirect("/")
            else:
                if not CustomUser.objects.filter(username=username).exists():
                    context["error"] = find_error_by_key("email_log")
                else:
                    context["error"] = find_error_by_key("password2")

        for error in form.errors.keys():
            error_text = find_error_by_key(error)
            context["error"] = error_text
            break

    return render(request, "accounts/login.html", context)


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
                return redirect("/pages")

    for error in form.errors.keys():
        error_text = find_error_by_key(error)
        context["error"] = error_text
        break

    return render(request, "accounts/register.html", context)


@login_required
def custom_logout_view(request):
    logout(request)

    return redirect('/login/')
