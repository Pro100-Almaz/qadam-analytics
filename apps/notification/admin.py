from django.contrib import admin

from apps.notification.models import Notification
from core.admin_mixins import SoftDeleteAdminMixin


@admin.register(Notification)
class NotificationAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('user', 'type', 'title', 'is_read', 'created_at')
    list_filter = ('type', 'is_read')
    search_fields = ('user__username', 'title', 'message')
    ordering = ('-created_at',)
