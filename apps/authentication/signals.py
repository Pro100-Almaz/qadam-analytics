from django.contrib import messages
from django.contrib.auth import user_logged_in
from django.dispatch import receiver




@receiver(user_logged_in)
def show_role_message(sender, user, request, **kwargs):
    # role = user.primary_group()
    # if role:
    #     message = "You logged in as a " #+ role + "!"
    # else:
    message = "You have successfully logged in!"
    messages.success(request, message)

    from apps.notification.models import Notification, LoginNotify
    notification = Notification.objects.create(user=user, action='login')
    LoginNotify.objects.create(notification=notification)