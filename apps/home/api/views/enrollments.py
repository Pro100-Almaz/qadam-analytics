from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.home.models import Enrollment
from apps.home.api.permissions import IsTeacherAdminOrSupervisor
from apps.home.api.serializers import EnrollmentSerializer


class EnrollmentListAPIView(ListAPIView):
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get_queryset(self):
        qs = Enrollment.objects.select_related(
            'class_group', 'class_group__grade_level', 'academic_year'
        )
        year_id = self.request.query_params.get('year')
        class_group_id = self.request.query_params.get('class_group')
        student_id = self.request.query_params.get('student')
        if year_id:
            qs = qs.filter(academic_year_id=year_id)
        if class_group_id:
            qs = qs.filter(class_group_id=class_group_id)
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs
