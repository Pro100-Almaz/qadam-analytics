from io import StringIO

from django.core.management import call_command
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.home.models import AcademicYear, ClassGroup
from apps.home.api.serializers import AcademicYearSerializer, ClassGroupSerializer
from core.permissions import IsAdminRole


class AcademicYearListAPIView(ListAPIView):
    queryset = AcademicYear.objects.order_by('-year')
    serializer_class = AcademicYearSerializer
    pagination_class = None


class ClassGroupListAPIView(ListAPIView):
    serializer_class = ClassGroupSerializer
    pagination_class = None

    def get_queryset(self):
        qs = ClassGroup.objects.select_related(
            'grade_level', 'academic_year'
        ).order_by('grade_level__number', 'letter')
        year_id = self.request.query_params.get('year')
        if year_id:
            qs = qs.filter(academic_year_id=year_id)
        return qs


class RolloverInputSerializer(serializers.Serializer):
    new_year_name = serializers.CharField(max_length=40)
    confirm = serializers.BooleanField()
    dry_run = serializers.BooleanField(default=False)


class RolloverAcademicYearAPIView(APIView):
    """POST /api/v1/admin/rollover-year/ — trigger academic year rollover."""
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        ser = RolloverInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        if not ser.validated_data['confirm']:
            return Response(
                {'detail': 'Set confirm=true to proceed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out = StringIO()
        args = [ser.validated_data['new_year_name']]
        kwargs = {'stdout': out, 'stderr': out}
        if ser.validated_data['dry_run']:
            kwargs['dry_run'] = True

        try:
            call_command('rollover_academic_year', *args, **kwargs)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'detail': 'Rollover completed.',
            'output': out.getvalue(),
        })
