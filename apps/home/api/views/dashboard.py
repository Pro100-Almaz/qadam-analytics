from rest_framework.response import Response
from rest_framework.views import APIView

from apps.home.services import get_dashboard_stats
from apps.home.api.serializers import DashboardStatsSerializer


class DashboardStatsAPIView(APIView):
    def get(self, request):
        data = get_dashboard_stats()
        return Response(DashboardStatsSerializer(data).data)
