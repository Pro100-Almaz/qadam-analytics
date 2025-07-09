from django.contrib.auth.decorators import login_required
from .models import Notification, RegisterNotify, LoginNotify, GradingNotify, PsychologicalNotify


def notifications_context(request):
    if not request.user.is_authenticated:
        return {}
    notifications = Notification.objects.filter(user=request.user).order_by('-send_time')
    total_notify = []

    for notification in notifications:
        try:
            if notification.action == "register":
                notify = RegisterNotify.objects.get(notification=notification)
            elif notification.action == "login":
                notify = LoginNotify.objects.get(notification=notification)
            elif notification.action == "grading":
                notify = GradingNotify.objects.get(notification=notification)
            elif notification.action == "psychological_state":
                notify = PsychologicalNotify.objects.get(notification=notification)
            else:
                continue

            notify.send_time = notification .send_time
            notify.action = notification.action
            total_notify.append(notify)

        except Exception:
            continue

    return{
        "notifications_count": len(total_notify),
        "notifications": total_notify
    }

