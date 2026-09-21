from io import StringIO

from django.core.management import call_command
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Parent, Student
from apps.home.models import AcademicYear, ClassGroup, ClassGroupCollection, Enrollment
from apps.home.api.serializers import (
    AcademicYearSerializer, ClassGroupSerializer, ClassGroupStudentSerializer,
)
from core.error_messages import NO_PERMISSION
from core.permissions import IsAdminRole, is_admin_role, is_staff_role, is_teacher_role


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
        category = self.request.query_params.get('category')
        if category in dict(ClassGroup.CATEGORY_CHOICES):
            qs = qs.filter(category=category)
        return qs


class ClassGroupMinorGroupListAPIView(ListAPIView):
    """GET class-groups/<pk>/minor-groups/ — the подгруппы bound to one class.

    Empty for a class with no constellation, and for a subgroup itself: only
    major class groups hold one.
    """
    serializer_class = ClassGroupSerializer
    pagination_class = None

    def get_queryset(self):
        class_group = get_object_or_404(ClassGroup, pk=self.kwargs['pk'])
        return ClassGroupCollection.minor_groups_of(class_group).select_related(
            'grade_level', 'academic_year'
        ).order_by('grade_level__number', 'letter')


def can_view_class_group_roster(user, class_group):
    """Staff see any roster; a student or parent only one they belong to."""
    if is_admin_role(user) or is_teacher_role(user) or is_staff_role(user):
        return True

    if user.is_student():
        students = Student.objects.filter(user=user)
    elif user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        students = parent.students.all() if parent else Student.objects.none()
    else:
        return False

    return Enrollment.objects.filter(
        student__in=students, class_group=class_group, status='active',
    ).exists()


class ClassGroupStudentListAPIView(ListAPIView):
    """GET class-groups/<pk>/students/ — the students enrolled in one class group.

    A подгруппа has a roster on exactly the same terms as a class. Defaults to
    the active enrollments; `?status=` takes any enrollment status, or `all`.
    """
    serializer_class = ClassGroupStudentSerializer
    pagination_class = None

    def get_queryset(self):
        class_group = get_object_or_404(ClassGroup, pk=self.kwargs['pk'])
        if not can_view_class_group_roster(self.request.user, class_group):
            raise PermissionDenied(NO_PERMISSION)

        status_param = self.request.query_params.get('status', 'active')
        if status_param == 'all':
            enrollments = Enrollment.objects.filter(
                class_group=class_group
            ).select_related('student', 'student__user')
        elif status_param in dict(Enrollment.STATUS_CHOICES):
            enrollments = Enrollment.get_students_in_class(
                class_group, status=status_param,
            )
        else:
            raise DRFValidationError({
                'status': (
                    'Invalid status. Use one of: '
                    f"{', '.join(dict(Enrollment.STATUS_CHOICES))}, all."
                )
            })

        return enrollments.order_by(
            'student__user__last_name', 'student__user__first_name',
        )


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
