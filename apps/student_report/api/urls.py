from django.urls import path

from apps.student_report.api.views import GenerateReportView, ReportDetailView, StudentReportListView
from apps.student_report.api.pdf_export import ReportPDFExportView
from apps.student_report.api.grade_sheets import (
    ClassGroupGradeSheetView,
    StudentGradeSheetView,
)

app_name = 'student-report-api'

urlpatterns = [
    path(
        'students/<int:student_id>/reports/generate/',
        GenerateReportView.as_view(),
        name='generate-report',
    ),
    path(
        'students/<int:student_id>/reports/',
        StudentReportListView.as_view(),
        name='report-list',
    ),
    path(
        'reports/<int:pk>/',
        ReportDetailView.as_view(),
        name='report-detail',
    ),
    path(
        'reports/<int:pk>/pdf/',
        ReportPDFExportView.as_view(),
        name='report-pdf',
    ),

    # XLSX grade sheets
    path(
        'grade/classgroup/<int:class_group_id>/',
        ClassGroupGradeSheetView.as_view(),
        name='class-group-grade-sheet',
    ),
    path(
        'grade/student/<int:student_id>/',
        StudentGradeSheetView.as_view(),
        name='student-grade-sheet',
    ),
]
