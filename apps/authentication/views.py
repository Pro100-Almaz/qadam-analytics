import random

from django.contrib import messages
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, user_logged_in
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpRequest, HttpResponseRedirect
from django.core.signing import Signer
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse

from core import settings
from .forms import LoginForm, SignUpForm, ForgetPasswordForm, VerificationPasswordForm, ResetPasswordForm
from .models import CustomUser, Teacher, Parent, Supervisor, Student
from apps.authentication.services import get_user_service
from errors import find_error_by_key


def login_view(request):
    form = LoginForm(request.POST or None)
    context = {"form": form}

    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data.get("username")
        password = form.cleaned_data.get("password")
        result = get_user_service().authenticate_and_login(request, username, password)
        if result.ok:
            return redirect("/")
        context["error"] = find_error_by_key(result.error_key)

    if request.method == "POST" and not form.is_valid():
        for key in form.errors.keys():
            context["error"] = find_error_by_key(key)
            break

    return render(request, "accounts/login.html", context)


def register_user(request):
    form = SignUpForm(request.POST or None, request.FILES or None)
    context = {"form": form}

    if request.method == "POST":
        user, error_message, redirect_url = get_user_service().register_user(request, form)
        if error_message:
            context["error"] = error_message
        else:
            return redirect(redirect_url)

    return render(request, "accounts/register.html", context)


def reset_password_view(request, uidb64, token):
    user = get_user_service().validate_reset_link(uidb64, token)
    if not user:
        messages.error(request, "Invalid link or token.")
        return render(request, "accounts/reset_password.html", {"link": False})

    form = ResetPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_password = form.cleaned_data.get("new_password")
        confirm_password = form.cleaned_data.get("confirm_password")
        if new_password != confirm_password:
            messages.error(request, "Пароли не совпадают")
        else:
            get_user_service().set_new_password(user, new_password)
            messages.success(request, "Пароль успешно изменен!")
            return redirect("login")

    return render(request, "accounts/reset_password.html", {"form": form, "link": True})


def forget_password_view(request):
    form = ForgetPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data.get("username")
        return get_user_service().start_password_change_flow(request, username)
    return render(request, "accounts/forget_password.html", {"form": form})


def verification_code_check(request, username, signed_code):
    user = get_object_or_404(CustomUser, username=username)
    form = VerificationPasswordForm(request.POST or None)

    if request.method == "POST":
        entered = request.POST.get("verification_code", "")
        ok, error = get_user_service().check_verification_code(signed_code, entered)
        if ok:
            return redirect("password_change", username=user.username, signed_code=signed_code)
        form.add_error("verification_code", error or "Неверный код.")

    return render(request, "accounts/verification_waitlist.html", {"form": form})


def password_change_final(request, username, signed_code):
    user = get_object_or_404(CustomUser, username=username)
    form = VerificationPasswordForm(request.POST or None)

    if request.method == "POST":
        pw1 = request.POST.get("password1", "")
        pw2 = request.POST.get("password2", "")
        ok, error = get_user_service().change_password_with_code(user, pw1, pw2)
        if ok:
            return redirect("login")
        messages.error(request, error or "Ошибка")

    return render(request, "accounts/password_change_final.html", {"form": form})


@login_required
def custom_logout_view(request):
    get_user_service().logout_user(request)
    return redirect("/login/")

# @receiver(user_logged_in)
# def show_log_in_notification(sender, request, user = CustomUser, **kwargs):
#     message = str(user.role)

def reset_password_link(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = request.build_absolute_uri(f"/reset/{uid}/{token}/")

    subject = "Reset Password"
    message = render_to_string(
        "email/reset_password_email.html",
        context={
            "subject": subject,
            "user": user,
            "url": url,
        }
    )
    from_mail = settings.DEFAULT_FROM_EMAIL
    to_mail = [user.email]

    email = EmailMultiAlternatives(subject, "", from_mail, to_mail)
    email.attach_alternative(message, "text/html")
    email.send()


def send_email_password_change(request, username):
    user = CustomUser.objects.filter(username=username).first()
    if not user:
        return redirect('/login/')


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
