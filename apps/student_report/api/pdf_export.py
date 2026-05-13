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
                'student__user', 'student__school_group',
                'academic_year', 'generated_by',
            ).get(pk=pk, status=StudentReport.Status.COMPLETED)
        except StudentReport.DoesNotExist:
            return Response(
                {'detail': 'Report not found or not completed.'},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        generated_by_name = ''
        if report.generated_by:
            generated_by_name = (
                report.generated_by.get_full_name()
                or report.generated_by.username
            )

        ai = report.report_data or {}
        snapshot = report.input_snapshot or {}
        grades_data = snapshot.get('grades', {})
        subjects_grades = grades_data.get('subjects', {})
        trends_data = snapshot.get('trends', {})
        class_context = snapshot.get('class_context', {})
        ai_subjects = ai.get('subject_analyses', {})

        subjects = []
        for name, quarters in subjects_grades.items():
            ai_entry = ai_subjects.get(name, {})
            trend_info = trends_data.get(name, {})
            subjects.append({
                'name': name,
                'q1': quarters.get('q1'),
                'q2': quarters.get('q2'),
                'q3': quarters.get('q3'),
                'q4': quarters.get('q4'),
                'cumulative': quarters.get('cumulative'),
                'class_avg': class_context.get(name),
                'trend': trend_info.get('direction', 'insufficient_data'),
                'analysis': ai_entry.get('analysis', ''),
                'recommendation': ai_entry.get('recommendation', ''),
            })

        context = {
            'report': report,
            'ai': ai,
            'subjects': subjects,
            'student_total_grade': grades_data.get('student_total_grade'),
            'student_name': report.student.user.get_full_name(),
            'class_group': str(report.student.school_group) if report.student.school_group else '',
            'academic_year': str(report.academic_year),
            'quarter_label': f'{report.quarter}-я четверть',
            'language': report.language,
            'school_name': getattr(report.student.user, 'school', '') or '',
            'generated_by_name': generated_by_name,
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
