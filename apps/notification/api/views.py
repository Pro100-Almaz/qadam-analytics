from rest_framework.generics import ListAPIView, RetrieveAPIView, DestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notification.models import Notification
from .serializers import NotificationSerializer


class NotificationListAPIView(ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Notification.objects
            .filter(user=self.request.user)
            .select_related(
                'registernotify',
                'loginnotify',
                'gradingnotify',
                'gradingnotify__lesson',
                'psychologicalnotify',
                'psychologicalnotify__psychologist',
            )
            .order_by('-send_time')
        )


class NotificationDetailAPIView(RetrieveAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Notification.objects
            .filter(user=self.request.user)
            .select_related(
                'registernotify',
                'loginnotify',
                'gradingnotify',
                'gradingnotify__lesson',
                'psychologicalnotify',
                'psychologicalnotify__psychologist',
            )
        )


class NotificationCountAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(user=request.user).count()
        return Response({'count': count})


class NotificationDeleteAPIView(DestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)
