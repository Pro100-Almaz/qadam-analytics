from rest_framework.generics import ListAPIView

from apps.home.models import AcademicYear, ClassGroup
from apps.home.api.serializers import AcademicYearSerializer, ClassGroupSerializer


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
