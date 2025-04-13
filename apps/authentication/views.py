# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

# Create your views here.
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

from .forms import LoginForm, SignUpForm


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

    if request.method == "POST":
        data = request.POST

        print(data)
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

    return render(request, "accounts/register.html", {"context": context, "msg": msg, "success": success})


@login_required
def custom_logout_view(request):
    logout(request)

    return redirect('/login/')
