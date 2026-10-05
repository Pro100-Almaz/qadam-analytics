from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Teacher, Student
from apps.home.models import (
    AcademicYear, ClassGroup, SubjectOffering, TeachingAssignment,
)
from apps.home.services_teacher import (
    get_lesson_teacher_dashboard,
    get_homeroom_dashboard,
    get_psychologist_dashboard,
    get_psychologist_student_detail,
    get_teacher_classes,
    get_class_students,
)
from apps.lesson.api.analytics_common import (
    OFFERING_SELECT_RELATED,
    academic_year_payload,
    bool_param,
    class_group_payload,
    int_param,
    offering_payload,
)
from core.permissions import (
    IsStaffOrAdmin, IsHomeroomTeacher,
    IsPsychologistOrAdmin, IsTeacherRole, is_admin_role,
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


class HomeroomMyClassAPIView(APIView):
    """GET /api/v1/homeroom/my-class/ — the homeroom class, its students and offerings (spec 0012)."""
    permission_classes = [IsAuthenticated, IsHomeroomTeacher]

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


class TeacherOfferingListAPIView(APIView):
    """
    GET /api/v1/teacher/offerings/ — the offerings the caller teaches (spec 0012).

    Only offerings with a TeachingAssignment for the caller. A homeroom
    teacher's class offerings they do not teach are left out: those live on
    homeroom/my-class/.
    """
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                'academic_year', int,
                description='Academic year id. Defaults to the active academic year.',
            ),
            OpenApiParameter(
                'include_empty', bool,
                description=(
                    'Include offerings with no assignments yet. Default '
                    'true; false returns only offerings with at least one '
                    'assignment.'
                ),
            ),
        ],
    )
    def get(self, request):
        teacher = Teacher.objects.select_related('user').filter(
            user=request.user,
        ).first()
        if not teacher:
            return Response(
                {'detail': 'No teacher profile found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        year_id = int_param(request.query_params, 'academic_year', 1)
        if year_id is not None:
            academic_year = get_object_or_404(AcademicYear, pk=year_id)
        else:
            academic_year = AcademicYear.objects.filter(is_active=True).first()

        teacher_data = {
            'id': teacher.id,
            'user_id': teacher.user_id,
            'full_name': (
                teacher.user.get_full_name().strip() or teacher.user.username
            ),
            'username': teacher.user.username,
        }
        if academic_year is None:
            return Response({
                'teacher': teacher_data,
                'academic_year': None,
                'offerings': [],
                'count': 0,
            })

        # An offering's year is its class group's — `academic_year` is a derived
        # property on the model, not a column, so it has to be traversed.
        roles_by_offering = dict(
            TeachingAssignment.objects.filter(
                teacher=teacher,
                offering__class_group__academic_year=academic_year,
            ).order_by('-id').values_list('offering_id', 'role')
        )

        offerings_qs = SubjectOffering.objects.filter(
            id__in=roles_by_offering,
            subject__status='active',
        )
        if not bool_param(request.query_params, 'include_empty', True):
            offerings_qs = offerings_qs.filter(assignments__isnull=False)

        offerings = (
            offerings_qs
            .select_related(*OFFERING_SELECT_RELATED)
            .distinct()
            .order_by(
                'class_group__grade_level__number',
                'class_group__letter',
                'subject__name',
                'id',
            )
        )

        rows = []
        for offering in offerings:
            row = offering_payload(offering)
            row.update({
                'subject_language_group': offering.subject.language_group,
                'class_group_id': offering.class_group_id,
                'class_group_detail': class_group_payload(offering.class_group),
                'academic_year_id': offering.academic_year_id,
                'teaching_role': roles_by_offering[offering.id],
            })
            rows.append(row)

        return Response({
            'teacher': teacher_data,
            'academic_year': academic_year_payload(academic_year),
            'offerings': rows,
            'count': len(rows),
        })


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
            request=request,
            teacher=None if (is_admin_role(request.user) or show_all) else teacher,
        )
        return Response(data)
