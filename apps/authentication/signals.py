from django.contrib import messages
from django.contrib.auth import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def show_role_message(sender, user, request, **kwargs):
    """Record a login notification for the user who just signed in.

    The scope is resolved from `user.school_id`, not from the ambient one. This
    signal fires *during* the login POST — and the scope middleware already ran,
    at which point `request.user` was still anonymous, so the ambient scope is
    UNSET. Under fail-closed scoping that made every admin login 500 on the
    `Notification.objects.create()` below.

    Same rule as `assign_intake_year_for_student`: derive the tenant from the
    object you are writing, so the code works in a request, a script, the shell
    and a Celery worker alike.
    """
    message = "You logged in as a "  # + getattr(user, 'role', None)
    messages.success(request, message)

    from apps.notification.models import Notification
    from core.tenancy import all_schools, school_scope

    # A schoolless superuser (createsuperuser) has no tenant to scope to.
    scope = school_scope(user.school_id) if user.school_id else all_schools()
    with scope:
        Notification.objects.create(
            user=user,
            type=Notification.NotificationType.LOGIN,
            title='Login',
            message='User logged in successfully',
        )
