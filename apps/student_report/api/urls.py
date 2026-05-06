from django.urls import path

from .views import GenerateReportView, ReportDetailView, StudentReportListView
from .pdf_export import ReportPDFExportView

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
]
