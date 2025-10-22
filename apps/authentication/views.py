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
            print(f"LOGIN DEBUG - Authentication result: {user}")
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

@receiver(user_logged_in)
def show_log_in_notification(sender, request, user = CustomUser, **kwargs):
    message = str(user.role)


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
                user.save()

                # Handle avatar upload
                if 'avatar' in request.FILES:
                    user.avatar = request.FILES['avatar']
                    user.save()

                if user.role == CustomUser.ROLE_TEACHER:
                    Teacher.objects.create(
                        user=user,
                        gender=form.cleaned_data['gender'],
                        academic_degree=form.cleaned_data['academic_degree'],
                        employment_type=form.cleaned_data['employment_type'],
                        occupation=form.cleaned_data['occupation'],
                        classroom=form.cleaned_data['classroom']
                    )
                if user.is_student():
                    Student.objects.create(
                        user=user,
                        school_group=form.cleaned_data['school_group'],
                        classroom=form.cleaned_data['classroom']
                    )
                elif user.is_manager():
                    Supervisor.objects.create(user=user)

                reset_password_link(request, user)

                login(request, user)
                if user.is_parent:
                    return redirect("/pages/teachers")
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


def reset_password_view(request, token, uidb64):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    if user and default_token_generator.check_token(user, token):
        form = ResetPasswordForm(request.POST or None)

        if request.method == "POST":
            new_password = form.cleaned_data.get("new_password")
            confirm_password = form.cleaned_data.get("confirm_password")

            if new_password != confirm_password:
                messages.error(request, "Пароли не совпадают")
            else:
                user.set_password(new_password)
                user.save()
                messages.success(request, "Пароль успешно изменен!")
                return redirect('login')

        return render(request, 'accounts/reset_password.html', {'form': form, 'link': True})
    else:
        messages.error(request, "Invalid link or token.")
        return render(request, 'accounts/reset_password.html', {'link': False})



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


def forget_password_view(request):
    form = ForgetPasswordForm(request.POST or None)
    context = {"form": form}

    if request.method == "POST":
        if form.is_valid():
            username = form.cleaned_data.get("username")
            return  send_email_password_change(request, username)
    return render(request, 'accounts/forget_password.html', context)


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

        if pw1 != pw2:
            messages.error(request, "Пароли не совпадают.")
        else:
            user.set_password(pw1)
            user.save()
            return redirect("login")

    return render(request, "accounts/password_change_final.html", {"form": form})


@login_required
def custom_logout_view(request):
    form = ForgetPasswordForm()
    logout(request)

    return redirect('/login/')




