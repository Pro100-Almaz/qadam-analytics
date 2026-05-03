from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView, CreateAPIView, DestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student, Teacher, Parent
from apps.home.models import (
    AcademicYear, Subject, SubjectOffering, TeachingAssignment, Enrollment,
)
from apps.home.services import get_subject_grades
from core.permissions import can_access_subject, can_modify_subject, is_admin_role, is_teacher_role
from core.error_messages import NO_ACCESS_SUBJECT, NO_MODIFY_SUBJECT

from apps.home.api.permissions import IsTeacherAdminOrSupervisor, IsAdminOrSupervisor
from apps.home.api.serializers import (
    SubjectSerializer,
    SubjectCreateSerializer,
    SubjectDetailSerializer,
    SubjectStatusSerializer,
)


class SubjectListAPIView(ListAPIView):
    serializer_class = SubjectSerializer

    def get_queryset(self):
        user = self.request.user
        status_filter = self.request.query_params.get('status', 'active')
        year_id = self.request.query_params.get('year')
        lang_filter = self.request.query_params.get('lang')

        if not year_id:
            current = AcademicYear.objects.order_by('-year').first()
            year_id = str(current.id) if current else None

        if is_admin_role(user):
            if status_filter == 'all':
                subjects = Subject.objects.all()
            elif status_filter in ('archived', 'disabled'):
                subjects = Subject.objects.filter(status__in=['archived', 'disabled'])
            elif status_filter == 'planned':
                subjects = Subject.objects.filter(status='planned')
            else:
                subjects = Subject.objects.filter(status='active')

        elif is_teacher_role(user):
            try:
                teacher = Teacher.objects.get(user=user)
                assignments = TeachingAssignment.objects.filter(teacher=teacher)
                if year_id:
                    assignments = assignments.filter(offering__academic_year_id=year_id)
                subject_ids = set(a.offering.subject_id for a in assignments)
                subjects = Subject.objects.filter(id__in=subject_ids)
                if status_filter != 'all':
                    subjects = subjects.filter(status=status_filter)
            except Teacher.DoesNotExist:
                subjects = Subject.objects.none()

        elif user.is_parent():
            try:
                parent = Parent.objects.get(user=user)
                children = parent.students.all()
                child_enrollments = Enrollment.objects.filter(
                    student__in=children, status='active'
                )
                if year_id:
                    child_enrollments = child_enrollments.filter(academic_year_id=year_id)
                class_group_ids = child_enrollments.values_list('class_group_id', flat=True)
                offerings = SubjectOffering.objects.filter(class_group_id__in=class_group_ids)
                if year_id:
                    offerings = offerings.filter(academic_year_id=year_id)
                subject_ids = offerings.values_list('subject_id', flat=True)
                subjects = Subject.objects.filter(id__in=subject_ids)
                if status_filter != 'all':
                    subjects = subjects.filter(status=status_filter)
            except Parent.DoesNotExist:
                subjects = Subject.objects.none()

        elif user.is_student():
            try:
                student = Student.objects.get(user=user)
                enrollments = Enrollment.objects.filter(
                    student=student, status='active'
                )
                if year_id:
                    enrollments = enrollments.filter(academic_year_id=year_id)
                class_group_ids = enrollments.values_list('class_group_id', flat=True)
                offerings = SubjectOffering.objects.filter(class_group_id__in=class_group_ids)
                if year_id:
                    offerings = offerings.filter(academic_year_id=year_id)
                subject_ids = offerings.values_list('subject_id', flat=True)
                subjects = Subject.objects.filter(id__in=subject_ids)
                if status_filter != 'all':
                    subjects = subjects.filter(status=status_filter)
            except Student.DoesNotExist:
                subjects = Subject.objects.none()
        else:
            subjects = Subject.objects.none()

        if lang_filter and lang_filter != 'all':
            subjects = subjects.filter(language_group=lang_filter)

        return subjects


class SubjectCreateAPIView(CreateAPIView):
    serializer_class = SubjectCreateSerializer
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subject = serializer.save()
        return Response(
            SubjectSerializer(subject).data,
            status=status.HTTP_201_CREATED,
        )


class SubjectDetailAPIView(RetrieveAPIView):
    serializer_class = SubjectDetailSerializer
    queryset = Subject.objects.select_related('added_by')

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if not can_access_subject(request.user, obj):
            self.permission_denied(request, message=(
                NO_ACCESS_SUBJECT
            ))


class SubjectGradesAPIView(APIView):
    def get(self, request, pk):
        quarter = int(request.query_params.get('quarter', 1))
        subject = Subject.objects.get(pk=pk)

        result = get_subject_grades(subject, request.user, quarter)
        if result is None:
            return Response(
                {'detail': 'You do not have permission to view this subject.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(result)


class SubjectStatusAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, pk):
        subject = Subject.objects.get(pk=pk)
        if not can_modify_subject(request.user, subject):
            return Response(
                {'detail': NO_MODIFY_SUBJECT},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SubjectStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']

        status_map = {
            'archive': 'archived',
            'activate': 'active',
            'plan': 'planned',
        }
        subject.status = status_map[action]
        subject.save()
        return Response(SubjectSerializer(subject).data)


class SubjectDeleteAPIView(DestroyAPIView):
    queryset = Subject.objects.all()
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]


class MySubjectsListAPIView(ListAPIView):
    serializer_class = SubjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        status_filter = self.request.query_params.get('status', 'active')

        try:
            teacher = Teacher.objects.get(user=user)
        except Teacher.DoesNotExist:
            return Subject.objects.none()

        assignments = TeachingAssignment.objects.filter(
            teacher=teacher
        ).select_related('offering__subject')
        subject_ids = set(a.offering.subject_id for a in assignments)
        qs = Subject.objects.filter(id__in=subject_ids)
        if status_filter != 'all':
            qs = qs.filter(status=status_filter)
        return qs
