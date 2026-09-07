from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Teacher, Parent
from apps.home.models import TeachingAssignment, Enrollment
from core.permissions import is_admin_role, is_teacher_role

from apps.home.api.permissions import (
    IsTeacherAdminOrSupervisor, IsAdminOrSupervisor, IsParent,
)
from core.error_messages import NO_ACCESS_TEACHER
from apps.home.api.serializers import (
    TeacherListSerializer,
    TeacherDetailSerializer,
    TeacherProfileUpdateSerializer,
)


class TeacherListAPIView(ListAPIView):
    serializer_class = TeacherListSerializer
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get_queryset(self):
        return Teacher.objects.select_related('user').order_by(
            'user__last_name', 'user__first_name', 'id',
        )


class TeacherDetailAPIView(RetrieveAPIView):
    serializer_class = TeacherDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'user_id'
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Teacher.objects.select_related('user')

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        user = request.user

        if is_admin_role(user) or is_teacher_role(user):
            return

        if user.is_parent():
            parent = Parent.objects.get(user=user)
            children = parent.students.all()
            has_link = TeachingAssignment.objects.filter(
                teacher=obj,
                offering__class_group__enrollments__student__in=children,
                offering__class_group__enrollments__status='active',
            ).exists()
            if has_link:
                return

        self.permission_denied(request, message=(
            NO_ACCESS_TEACHER
        ))


class TeacherProfileUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def patch(self, request, pk):
        teacher = Teacher.objects.select_related('user').get(pk=pk)
        serializer = TeacherProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = teacher.user
        for field in ('email', 'first_name', 'last_name', 'phone_number', 'date_of_birth', 'address'):
            if field in data:
                setattr(user, field, data[field])
        user.save()

        for field in ('gender', 'academic_degree', 'employment_type', 'occupation'):
            if field in data:
                setattr(teacher, field, data[field])
        teacher.save()

        return Response(TeacherDetailSerializer(teacher).data)


class ParentTeacherListAPIView(ListAPIView):
    serializer_class = TeacherListSerializer
    permission_classes = [IsAuthenticated, IsParent]

    def get_queryset(self):
        parent = Parent.objects.get(user=self.request.user)
        students = parent.students.all()

        enrollments = Enrollment.objects.filter(
            student__in=students, status='active', academic_year__is_active=True,
        ).select_related('class_group')
        class_groups = [e.class_group for e in enrollments]

        assignments = TeachingAssignment.objects.filter(
            offering__class_group__in=class_groups,
            offering__academic_year__is_active=True,
        ).select_related('teacher', 'teacher__user', 'offering__subject')

        teacher_ids = set()
        for a in assignments:
            teacher_ids.add(a.teacher_id)

        return Teacher.objects.filter(id__in=teacher_ids).select_related('user').order_by(
            'user__last_name', 'user__first_name', 'id',
        )
