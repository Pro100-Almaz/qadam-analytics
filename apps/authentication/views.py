import random

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpRequest, HttpResponseRedirect
from django.core.signing import Signer

from core import settings
from .forms import LoginForm, SignUpForm, ForgetPasswordForm, VerificationPasswordForm
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
        form = SignUpForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            user.username = user.email
            
            if CustomUser.objects.filter(username=user.username).exists():
                context["error"] = find_error_by_key("email")
            else:
                # Handle avatar upload
                if 'avatar' in request.FILES:
                    user.avatar = request.FILES['avatar']
                user.save()
                login(request, user)
                return redirect("/pages")
        else:
            # Add form errors to context
            for field, errors in form.errors.items():
                for error in errors:
                    context["error"] = error
                    break
                if context.get("error"):
                    break

    return render(request, "accounts/register.html", context)

def forget_password_view(request):
    form = ForgetPasswordForm(request.POST or None)
    context = {"form": form}

    if request.method == "POST":
        if form.is_valid():
            username = form.cleaned_data.get("username")
            return  send_email_password_change(request, username)
    return render(request, 'accounts/forget_password.html', context)


def send_email_password_change(request, username):
    user = CustomUser.objects.filter(username=username).first()
    if not user:
        return redirect('authentication:login')


    verification_code = random.randint(100000, 999999)

    subject = "Verification email"
    message = render_to_string("email/verification_email.html", {"user": user, "verification_code": verification_code})
    from_mail = settings.DEFAULT_FROM_EMAIL
    to_mail = [user.email]

    email = EmailMultiAlternatives(subject, "", from_mail, to_mail)
    email.attach_alternative(message, "text/html")
    email.send()

    signer = Signer()
    signed_code = signer.sign(str(verification_code))

    return redirect("verification_code", username=user.username, signed_code=signed_code)

#
def verification_code_check(request, username, signed_code):
    user = get_object_or_404(CustomUser, username=username)
    form = VerificationPasswordForm(request.POST or None)
    signer = Signer()

    if request.method == "POST":

        entered = request.POST.get("verification_code")
        if not entered.isdigit():
            form.add_error('verification_code', "Неверный код.")
            return render(request, "accounts/verification_waitlist.html", {"form": form})

        entered = int(entered)
        actual = int(signer.unsign(signed_code))

        if entered != actual:
            form.add_error('verification_code', "Неверный код.")
        else:
            return redirect("password_change", username=user.username, signed_code=signed_code)

    return render(request, "accounts/verification_waitlist.html", {"form": form})

def password_change_final(request, username, signed_code):
    user = get_object_or_404(CustomUser, username=username)
    form = VerificationPasswordForm(request.POST or None)

    if request.method == "POST":
        pw1 = request.POST.get("password1")
        pw2 = request.POST.get("password2")
        print("NNNNNNNNNNNNNNNNNNNNNNNNNNNNN")

        if pw1 != pw2:
            messages.error(request, "Пароли не совпадают.")
        else:
            user.set_password(pw1)
            user.save()
            print("EEEEEEEEEEEEEEEEEEEEEEEEe")
            return redirect("login")

    return render(request, "accounts/password_change_final.html", {"form": form})


@login_required
def custom_logout_view(request):
    form = ForgetPasswordForm()
    logout(request)

    return redirect('/login/')

