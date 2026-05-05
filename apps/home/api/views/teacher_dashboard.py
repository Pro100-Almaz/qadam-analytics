from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Teacher, Student
from apps.home.models import ClassGroup
from apps.home.services_teacher import (
    get_lesson_teacher_dashboard,
    get_homeroom_dashboard,
    get_psychologist_dashboard,
    get_psychologist_student_detail,
    get_teacher_classes,
    get_class_students,
)
from core.permissions import (
    IsStaffOrAdmin, IsHomeroomTeacherOrAdmin,
    IsPsychologistOrAdmin, is_admin_role,
)


class TeacherRoleDashboardAPIView(APIView):
    """GET /api/v1/teacher/dashboard/ — auto-detects teacher subtype and returns appropriate data."""
    permission_classes = [IsAuthenticated, IsStaffOrAdmin]

    def get(self, request):
        user = request.user

        role_data = {
            'user_id': user.id,
            'full_name': user.get_full_name(),
            'roles': list(user.groups.values_list('name', flat=True)),
            'dashboards': {},
        }

        teacher = Teacher.objects.filter(user=user).first()

        if user.groups.filter(name='Teacher').exists() and teacher:
            role_data['dashboards']['lesson_teacher'] = get_lesson_teacher_dashboard(teacher)

        if user.groups.filter(name='HomeroomTeacher').exists() and teacher:
            role_data['dashboards']['homeroom_teacher'] = get_homeroom_dashboard(teacher)

        if user.groups.filter(name='Psychologist').exists():
            role_data['dashboards']['psychologist'] = get_psychologist_dashboard(user)

        if is_admin_role(user) and teacher:
            role_data['dashboards']['lesson_teacher'] = get_lesson_teacher_dashboard(teacher)

        return Response(role_data)


class HomeroomClassAPIView(APIView):
    """GET /api/v1/teacher/my-class/ — homeroom teacher's class with student grades overview."""
    permission_classes = [IsAuthenticated, IsHomeroomTeacherOrAdmin]

    def get(self, request):
        teacher = Teacher.objects.filter(user=request.user).first()
        if not teacher:
            return Response(
                {'detail': 'No teacher profile found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = get_homeroom_dashboard(teacher)
        if not data.get('class_group'):
            return Response(
                {'detail': 'No homeroom class assigned for the current year.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(data)


class PsychologistDashboardAPIView(APIView):
    """GET /api/v1/teacher/psychologist/ — psychological states overview and stats."""
    permission_classes = [IsAuthenticated, IsPsychologistOrAdmin]

    def get(self, request):
        data = get_psychologist_dashboard(request.user)
        return Response(data)


class PsychologistStudentDetailAPIView(APIView):
    """GET /api/v1/teacher/psychologist/students/<pk>/ — student's psych state history."""
    permission_classes = [IsAuthenticated, IsPsychologistOrAdmin]

    def get(self, request, pk):
        try:
            data = get_psychologist_student_detail(pk)
        except Student.DoesNotExist:
            return Response(
                {'detail': 'Student not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(data)


class TeacherMyClassesAPIView(APIView):
    """GET /api/v1/teacher/my-classes/ — list of class groups the teacher is associated with."""
    permission_classes = [IsAuthenticated, IsStaffOrAdmin]

    def get(self, request):
        teacher = Teacher.objects.filter(user=request.user).first()
        if not teacher:
            return Response(
                {'detail': 'No teacher profile found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = get_teacher_classes(teacher)
        return Response(data)


class TeacherClassStudentsAPIView(APIView):
    """GET /api/v1/teacher/my-classes/<class_group_id>/students/ — students in a class."""
    permission_classes = [IsAuthenticated, IsStaffOrAdmin]

    def get(self, request, class_group_id):
        teacher = Teacher.objects.filter(user=request.user).first()
        if not teacher:
            return Response(
                {'detail': 'No teacher profile found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            ClassGroup.objects.get(pk=class_group_id)
        except ClassGroup.DoesNotExist:
            return Response(
                {'detail': 'Class group not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        show_all = request.query_params.get('all_subjects', '').lower() == 'true'
        data = get_class_students(
            class_group_id,
            teacher=None if (is_admin_role(request.user) or show_all) else teacher,
        )
        return Response(data)
