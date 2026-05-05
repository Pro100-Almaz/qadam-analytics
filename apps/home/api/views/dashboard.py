from datetime import date

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Teacher
from apps.home.services import get_dashboard_stats, get_teacher_workload
from apps.home.api.serializers import DashboardStatsSerializer
from core.permissions import IsTeacherAdminOrSupervisor


class DashboardStatsAPIView(APIView):
    def get(self, request):
        data = get_dashboard_stats()
        return Response(DashboardStatsSerializer(data).data)


class TeacherWorkloadAPIView(APIView):
    """GET /api/v1/dashboard/teacher-workload/ — teacher workload stats."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get(self, request):
        teacher_id = request.query_params.get('teacher_id')
        if teacher_id:
            teacher = Teacher.objects.filter(pk=teacher_id).first()
            if not teacher:
                return Response(
                    {'detail': 'Teacher not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            teacher = Teacher.objects.filter(user=request.user).first()
            if not teacher:
                return Response(
                    {'detail': 'No teacher profile found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        week_start = request.query_params.get('week_start')
        week_end = request.query_params.get('week_end')

        try:
            week_start = date.fromisoformat(week_start) if week_start else None
            week_end = date.fromisoformat(week_end) if week_end else None
        except ValueError:
            return Response(
                {'detail': 'Invalid date format. Use YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = get_teacher_workload(teacher, week_start, week_end)
        return Response(data)
