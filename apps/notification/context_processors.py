from .models import Notification


def notifications_context(request):
    if not request.user.is_authenticated:
        return {}

    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')

    return {
        "notifications_count": notifications.count(),
        "notifications": notifications,
    }
