import io

from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView
from weasyprint import HTML

from apps.student_report.models import StudentReport
from core.permissions import IsTeacherAdminOrSupervisor


class ReportPDFExportView(APIView):
    permission_classes = [IsTeacherAdminOrSupervisor]

    def get(self, request, pk):
        try:
            report = StudentReport.objects.select_related(
                'student__user', 'academic_year'
            ).get(pk=pk, status=StudentReport.Status.COMPLETED)
        except StudentReport.DoesNotExist:
            return Response(
                {'detail': 'Report not found or not completed.'},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        context = {
            'report': report,
            'data': report.report_data,
            'student_name': report.student.user.get_full_name(),
            'class_group': str(report.student.school_group) if report.student.school_group else '',
            'academic_year': str(report.academic_year),
            'quarter_label': f'Q{report.quarter}',
            'language': report.language,
        }

        html_string = render_to_string('student_report/report_pdf.html', context)
        buffer = io.BytesIO()
        HTML(string=html_string).write_pdf(buffer)
        buffer.seek(0)

        student_name = report.student.user.get_full_name().replace(' ', '_')
        filename = f"Report_{student_name}_Q{report.quarter}_{report.language}.pdf"

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
