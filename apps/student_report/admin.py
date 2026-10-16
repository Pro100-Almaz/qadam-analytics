from django.contrib import admin

from apps.student_report.models import StudentReport
from core.admin_mixins import SoftDeleteAdminMixin


@admin.register(StudentReport)
class StudentReportAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ['student', 'academic_year', 'quarter', 'language', 'status', 'created_at']
    list_filter = ['status', 'language', 'quarter', 'academic_year']
    readonly_fields = ['report_data', 'input_snapshot', 'tokens_used', 'generation_time_ms']
    raw_id_fields = ['student', 'generated_by']
