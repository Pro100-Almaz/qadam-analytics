from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from apps.student_report.models import StudentReport
from apps.student_report.api.serializers import (
    GenerateReportSerializer,
    StudentReportSerializer,
    StudentReportListSerializer,
)
from core.permissions import IsTeacherAdminOrSupervisor, IsParent, CanAccessStudent


class GenerateReportView(GenericAPIView):
    permission_classes = [IsTeacherAdminOrSupervisor]
    serializer_class = GenerateReportSerializer
    throttle_scope = 'ai_report'

    def post(self, request, student_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        language = serializer.validated_data['language']
        quarter = serializer.validated_data['quarter']

        from apps.home.models import AcademicYear
        academic_year = AcademicYear.objects.filter(is_active=True).first()
        if not academic_year:
            return Response(
                {'detail': 'No active academic year found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.authentication.models import Student
        if not Student.objects.filter(pk=student_id).exists():
            return Response(
                {'detail': 'Student not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        cache_cutoff = timezone.now() - timedelta(
            seconds=settings.AI_REPORT_CACHE_TTL
        )
        existing = StudentReport.objects.select_related(
            'student__user', 'student__school_group',
            'academic_year', 'generated_by',
        ).filter(
            student_id=student_id,
            academic_year=academic_year,
            quarter=quarter,
            language=language,
            status=StudentReport.Status.COMPLETED,
            created_at__gte=cache_cutoff,
        ).first()

        if existing:
            return Response(
                StudentReportSerializer(existing).data,
                status=status.HTTP_200_OK,
            )

        report = StudentReport.objects.create(
            student_id=student_id,
            academic_year=academic_year,
            quarter=quarter,
            language=language,
            generated_by=request.user,
        )

        from apps.student_report.tasks import generate_report_task
        generate_report_task.delay(report.pk)

        report = StudentReport.objects.select_related(
            'student__user', 'student__school_group',
            'academic_year', 'generated_by',
        ).get(pk=report.pk)

        return Response(
            StudentReportSerializer(report).data,
            status=status.HTTP_202_ACCEPTED,
        )


class ReportDetailView(RetrieveAPIView):
    permission_classes = [IsTeacherAdminOrSupervisor]
    serializer_class = StudentReportSerializer
    queryset = StudentReport.objects.select_related(
        'student__user', 'student__school_group',
        'academic_year', 'generated_by',
    )


class StudentReportListView(ListAPIView):
    permission_classes = [CanAccessStudent]
    serializer_class = StudentReportListSerializer

    def get_queryset(self):
        return StudentReport.objects.filter(
            student_id=self.kwargs['student_id'],
        ).select_related(
            'student__user', 'student__school_group',
            'academic_year', 'generated_by',
        ).order_by('-created_at')
