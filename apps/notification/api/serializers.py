from rest_framework import serializers

from apps.notification.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    message = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'action', 'send_time', 'message']

    def get_message(self, obj: Notification) -> str:
        if hasattr(obj, 'registernotify'):
            return obj.registernotify.get_message()
        if hasattr(obj, 'loginnotify'):
            return obj.loginnotify.get_message()
        if hasattr(obj, 'gradingnotify'):
            return obj.gradingnotify.get_message()
        if hasattr(obj, 'psychologicalnotify'):
            return obj.psychologicalnotify.get_message()
        return ''
