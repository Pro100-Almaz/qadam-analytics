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
    msg = None
    success = False
    context = {}
    form = SignUpForm()

    if request.method == "POST":
        data = request.POST
        form = SignUpForm(request.POST, request.FILES)
        print(data)
        if form.is_valid():
            user = form.save(commit=False)
            user.username = user.email
            if CustomUser.objects.filter(username=user.username).exists():
                form.add_error('email', "Email already registered")
            else:
                user.save()
                login(request, user)
                return redirect("/")
    else:
        school_list = [
            'Muzafar Alimbayev 21',
            'Bukhar Zhyrau 19/1'
        ]

        roles = ['Учитель', 'Ученик', 'Родитель']
        context = {
            'school_list': school_list,
            'roles': roles,
        }

    return render(request, "accounts/register.html", {"context": context, "msg": msg, "success": success, "form": form})


@login_required
def custom_logout_view(request):
    logout(request)

    return redirect('/login/')
