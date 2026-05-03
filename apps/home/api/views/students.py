from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student, PsychologicalState, PsychologicalStateTemplates
from apps.home.models import (
    AcademicYear, ClassGroup, SubjectOffering, TeachingAssignment, Enrollment,
)
from apps.lesson.models import Lesson
from apps.home.repo.students import grade_identifier
from apps.home.services import get_students_for_role
from apps.lesson.services import get_cached_grades_bulk
from core.permissions import can_access_student
from core.error_messages import NO_ACCESS_STUDENT, STUDENT_NOT_FOUND

from apps.home.api.permissions import (
    IsTeacherAdminOrSupervisor, IsAdminOrSupervisor, IsStudent,
)
from apps.home.api.serializers import (
    StudentListSerializer,
    StudentDetailSerializer,
    StudentProfileUpdateSerializer,
    PsychologicalStateCreateSerializer,
    PsychologicalStateTemplateSerializer,
    StudentMySubjectSerializer,
    StudentMyTeacherSerializer,
    StudentClassmateSerializer,
)


class StudentListAPIView(ListAPIView):
    serializer_class = StudentListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_students_for_role(
            self.request.user,
            year_id=self.request.query_params.get('year'),
            class_group_id=self.request.query_params.get('class_group'),
        )


class StudentDetailAPIView(RetrieveAPIView):
    serializer_class = StudentDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'user_id'
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Student.objects.select_related('user')

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if not can_access_student(request.user, obj):
            self.permission_denied(request, message=(
                NO_ACCESS_STUDENT
            ))


class StudentProfileUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def patch(self, request, pk):
        student = Student.objects.select_related('user').get(pk=pk)
        serializer = StudentProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = student.user
        for field in ('email', 'first_name', 'last_name', 'phone_number', 'date_of_birth', 'address'):
            if field in data:
                setattr(user, field, data[field])
        user.save()

        if 'school_group' in data and data['school_group']:
            from apps.authentication.models import SchoolGroup
            try:
                student.school_group = SchoolGroup.objects.get(id=data['school_group'])
            except SchoolGroup.DoesNotExist:
                pass

        if 'academic_year' in data and data['academic_year']:
            try:
                student.academic_year = AcademicYear.objects.get(id=data['academic_year'])
            except AcademicYear.DoesNotExist:
                pass

        if 'class_group' in data and data['class_group']:
            try:
                class_group = ClassGroup.objects.get(id=data['class_group'])
                academic_year = (
                    student.academic_year
                    or AcademicYear.objects.filter(is_active=True).first()
                )
                if academic_year:
                    Enrollment.enroll_student(student, class_group, academic_year)
            except ClassGroup.DoesNotExist:
                pass

        student.save()
        return Response(StudentDetailSerializer(student).data)


# ── Psychological States ──

class PsychologicalStateCreateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, pk):
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist:
            return Response(
                {'detail': STUDENT_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PsychologicalStateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not PsychologicalStateTemplates.objects.filter(name=data['state_name']).exists():
            PsychologicalStateTemplates.objects.create(
                name=data['state_name'],
                comment=data.get('comment', ''),
            )

        state = PsychologicalState.objects.create(
            name=data['state_name'],
            comment=data.get('comment', ''),
            score=data['score'],
            student=student,
            added_by=request.user,
        )
        return Response({
            'id': state.id,
            'name': state.name,
            'score': state.score,
            'comment': state.comment,
            'time_added': state.time_added.isoformat() if state.time_added else None,
        }, status=status.HTTP_201_CREATED)


class PsychologicalStateDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def delete(self, request, pk):
        try:
            obj = PsychologicalState.objects.select_related('student').get(pk=pk)
        except PsychologicalState.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if obj.student and not can_access_student(request.user, obj.student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PsychologicalStateTemplateListAPIView(ListAPIView):
    queryset = PsychologicalStateTemplates.objects.all()
    serializer_class = PsychologicalStateTemplateSerializer
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]
    pagination_class = None


# ── Student Self-Service ──

class StudentMySubjectsAPIView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        student = Student.objects.select_related('user').get(user=request.user)
        enrollment = student.get_current_enrollment()
        if not enrollment:
            return Response([])

        offerings = list(SubjectOffering.objects.filter(
            class_group=enrollment.class_group,
            academic_year=enrollment.academic_year,
        ).select_related('subject', 'class_group', 'class_group__grade_level'))

        offering_ids = [o.id for o in offerings]

        primary_assignments = TeachingAssignment.objects.filter(
            offering_id__in=offering_ids, role='primary',
        ).select_related('teacher__user')
        teacher_by_offering = {ta.offering_id: ta.teacher for ta in primary_assignments}

        lessons = list(Lesson.objects.filter(offering_id__in=offering_ids))
        grades_map = get_cached_grades_bulk(lessons, [student])

        result = []
        for offering in offerings:
            teacher = teacher_by_offering.get(offering.id)
            teacher_data = None
            if teacher:
                avatar_url = teacher.user.avatar.url if teacher.user.avatar else None
                teacher_data = {
                    'id': teacher.user.id,
                    'full_name': teacher.user.get_full_name(),
                    'avatar': avatar_url,
                }

            offering_lessons = [l for l in lessons if l.offering_id == offering.id]
            cumulative = 0
            quarter_grades = {}
            for q in (1, 2, 3, 4):
                q_lessons = [l for l in offering_lessons if l.quarter == q]
                if q_lessons:
                    q_grade_values = [grades_map.get((l.id, student.id), 0) for l in q_lessons]
                    avg = sum(q_grade_values) / len(q_grade_values)
                    quarter_grades[str(q)] = grade_identifier(avg)
                    cumulative += avg
                else:
                    quarter_grades[str(q)] = None

            active_quarters = sum(1 for v in quarter_grades.values() if v is not None)
            student_grade = round(cumulative / active_quarters, 1) if active_quarters else 0

            result.append({
                'offering_id': offering.id,
                'subject_id': offering.subject_id,
                'subject_name': offering.subject.name,
                'language': offering.subject.language_group,
                'teacher': teacher_data,
                'class_group_name': str(offering.class_group),
                'student_grade': student_grade,
                'quarter_grades': quarter_grades,
            })

        serializer = StudentMySubjectSerializer(result, many=True)
        return Response(serializer.data)


class StudentMyTeachersAPIView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        student = Student.objects.get(user=request.user)
        enrollment = student.get_current_enrollment()
        if not enrollment:
            return Response([])

        assignments = TeachingAssignment.objects.filter(
            offering__class_group=enrollment.class_group,
            offering__academic_year=enrollment.academic_year,
        ).select_related('teacher__user', 'offering__subject')

        teacher_map = {}
        for a in assignments:
            tid = a.teacher.id
            if tid not in teacher_map:
                avatar_url = a.teacher.user.avatar.url if a.teacher.user.avatar else None
                teacher_map[tid] = {
                    'id': a.teacher.user.id,
                    'full_name': a.teacher.user.get_full_name(),
                    'avatar': avatar_url,
                    'email': a.teacher.user.email,
                    'subjects': [],
                }
            subj_name = a.offering.subject.name
            if subj_name not in teacher_map[tid]['subjects']:
                teacher_map[tid]['subjects'].append(subj_name)

        serializer = StudentMyTeacherSerializer(list(teacher_map.values()), many=True)
        return Response(serializer.data)


class StudentClassmatesAPIView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        student = Student.objects.get(user=request.user)
        enrollment = student.get_current_enrollment()
        if not enrollment:
            return Response([])

        classmates = Student.objects.filter(
            enrollments__class_group=enrollment.class_group,
            enrollments__academic_year=enrollment.academic_year,
            enrollments__status='active',
        ).exclude(id=student.id).select_related('user').distinct()

        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            classmates = classmates.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search)
            )

        offerings = list(SubjectOffering.objects.filter(
            class_group=enrollment.class_group,
            academic_year=enrollment.academic_year,
        ))
        classmate_list = list(classmates)

        lessons = list(Lesson.objects.filter(offering__in=offerings))
        grades_map = get_cached_grades_bulk(lessons, classmate_list)

        result = []
        for cm in classmate_list:
            total = 0
            count = 0
            for lesson in lessons:
                grade = grades_map.get((lesson.id, cm.id), 0)
                total += grade
                count += 1
            avg = round(total / count, 1) if count else 0

            avatar_url = cm.user.avatar.url if cm.user.avatar else None
            result.append({
                'id': cm.id,
                'full_name': cm.user.get_full_name(),
                'avatar': avatar_url,
                'email': cm.user.email,
                'student_total_grade': avg,
            })

        serializer = StudentClassmateSerializer(result, many=True)
        return Response(serializer.data)
