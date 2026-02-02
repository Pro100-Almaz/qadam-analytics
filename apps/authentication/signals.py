from django.contrib import messages
from django.contrib.auth import user_logged_in
from django.dispatch import receiver




@receiver(user_logged_in)
def show_role_message(sender, user, request, **kwargs):
    message = "You logged in as a "
    messages.success(request, message)

    from apps.notification.models import Notification, LoginNotify
    notification = Notification.objects.create(user=user, action='login')
    LoginNotify.objects.create(notification=notification)