from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from .forms import LoginForm, SignUpForm, ForgetPasswordForm, VerificationPasswordForm, ResetPasswordForm
from .models import CustomUser
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
