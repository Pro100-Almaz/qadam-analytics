import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.core.signing import Signer, BadSignature
from django.db import transaction
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode

from core import settings
from .models import Teacher, Supervisor, Student, CustomUser
from errors import find_error_by_key


User: CustomUser = get_user_model()  # noqa


@dataclass
class AuthResult:
    ok: bool
    user: Optional[User] = None
    error_key: Optional[str] = None


class AccountService:
    """
    A cohesive service layer for account-related actions.
    Keeps views skinny and logic testable.
    """

    def authenticate_and_login(self, request, username: str, password: str) -> AuthResult:
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            return AuthResult(ok=True, user=user)

        # figure out whether it's an unknown email/username or a bad password
        if not User.objects.filter(username=username).exists():
            return AuthResult(ok=False, error_key="email_log")
        return AuthResult(ok=False, error_key="password2")

    @transaction.atomic
    def register_user(self, request, form) -> Tuple[Optional[User], Optional[str], Optional[str]]:
        """
        Returns: (user, error_message, redirect_url)
        - If success, user != None and redirect_url is where to go next.
        - If error, error_message is set.
        """
        if not form.is_valid():
            for _, errors in form.errors.items():
                return None, (errors[0] if errors else "Invalid data"), None
            return None, "Invalid data", None

        user = form.save(commit=False)
        user.username = user.email

        if User.objects.filter(username=user.username).exists():
            return None, find_error_by_key("email"), None

        user.save()

        if "avatar" in request.FILES:
            user.avatar = request.FILES["avatar"]
            user.save(update_fields=["avatar"])

        if user.is_teacher():
            Teacher.objects.create(
                user=user,
                gender=form.cleaned_data.get("gender"),
                academic_degree=form.cleaned_data.get("academic_degree"),
                employment_type=form.cleaned_data.get("employment_type"),
                occupation=form.cleaned_data.get("occupation"),
                classroom=form.cleaned_data.get("classroom"),
            )

        elif user.is_student():
            Student.objects.create(
                user=user,
                school_group=form.cleaned_data.get("school_group"),
                classroom=form.cleaned_data.get("classroom"),
            )
        elif user.is_manager():
            Supervisor.objects.create(user=user)

        self.send_reset_password_link(request, user)

        login(request, user)
        redirect_url = "/pages/teachers" if user.is_parent() else "/"
        return user, None, redirect_url

    def send_reset_password_link(self, request, user: CustomUser) -> None:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        reset_url = request.build_absolute_uri(f"/reset/{uid}/{token}/")

        subject = "Reset Password"
        html = render_to_string(
            "email/reset_password_email.html",
            {"subject": subject, "user": user, "url": reset_url},
        )
        self._send_html_email(subject, html, [user.email])

    def send_verification_code(self, user: CustomUser) -> str:
        """
        Sends a 6-digit code, returns signed_code (do not store in DB; stateless).
        """
        verification_code = random.randint(100_000, 999_999)
        subject = "Verification email"
        html = render_to_string(
            "email/verification_email.html",
            {"user": user, "verification_code": verification_code},
        )
        self._send_html_email(subject, html, [user.email])

        signer = Signer()
        return signer.sign(str(verification_code))

    def start_password_change_flow(self, request, username: str):
        """
        Either redirects to verification or back to login if user not found.
        """
        user = User.objects.filter(username=username).first()
        if not user:
            return redirect("/login/")

        signed_code = self.send_verification_code(user)
        return redirect("verification_code", username=user.username, signed_code=signed_code)

    def change_password_with_code(self, user: User, pw1: str, pw2: str) -> Tuple[bool, Optional[str]]:
        if pw1 != pw2:
            return False, "Пароли не совпадают."
        self.set_new_password(user, pw1)
        return True, None

    @staticmethod
    def validate_reset_link(uidb64: str, token: str) -> Optional[User]:
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None

        return user if default_token_generator.check_token(user, token) else None

    @staticmethod
    def set_new_password(user: User, new_password: str) -> None:
        user.set_password(new_password)
        user.save(update_fields=["password"])

    @staticmethod
    def check_verification_code(signed_code: str, entered: str) -> Tuple[bool, Optional[str]]:
        if not entered.isdigit():
            return False, "Неверный код."
        try:
            actual = int(Signer().unsign(signed_code))
        except BadSignature:
            return False, "Неверный код."
        return (int(entered) == actual), (None if int(entered) == actual else "Неверный код.")

    @staticmethod
    def logout_user(request):
        logout(request)

    @staticmethod
    def _send_html_email(subject: str, html: str, to: list[str]) -> None:
        email = EmailMultiAlternatives(subject, "", settings.DEFAULT_FROM_EMAIL, to)
        email.attach_alternative(html, "text/html")
        email.send()


@lru_cache
def get_user_service() -> AccountService:
    srv = AccountService()
    return srv
