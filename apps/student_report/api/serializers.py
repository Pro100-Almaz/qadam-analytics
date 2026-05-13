from rest_framework import serializers

from apps.student_report.models import StudentReport


class GenerateReportSerializer(serializers.Serializer):
    language = serializers.ChoiceField(
        choices=StudentReport.Language.choices,
        default='ru',
    )
    quarter = serializers.IntegerField(min_value=1, max_value=4)


class _ReportUserMixin:
    def get_generated_by_name(self, obj):
        if obj.generated_by:
            return obj.generated_by.get_full_name() or obj.generated_by.username
        return None

    def get_student_name(self, obj):
        return obj.student.user.get_full_name() or obj.student.user.username

    def get_class_group(self, obj):
        return str(obj.student.school_group) if obj.student.school_group else ''

    def get_academic_year_label(self, obj):
        return str(obj.academic_year) if obj.academic_year else ''


class StudentReportSerializer(_ReportUserMixin, serializers.ModelSerializer):
    generated_by_name = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    class_group = serializers.SerializerMethodField()
    academic_year_label = serializers.SerializerMethodField()

    class Meta:
        model = StudentReport
        fields = [
            'id', 'student', 'student_name', 'class_group',
            'academic_year', 'academic_year_label', 'quarter', 'language',
            'status', 'report_data', 'input_snapshot',
            'tokens_used', 'generation_time_ms',
            'generated_by', 'generated_by_name', 'created_at', 'error_message',
        ]


class StudentReportListSerializer(_ReportUserMixin, serializers.ModelSerializer):
    generated_by_name = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = StudentReport
        fields = [
            'id', 'student_name', 'quarter', 'language', 'status',
            'generated_by_name', 'created_at',
        ]
