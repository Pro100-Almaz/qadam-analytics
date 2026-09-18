from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student, PsychologicalState, PsychologicalStateTemplates
from apps.home.models import (
    AcademicYear, ClassGroup, SubjectOffering, TeachingAssignment, Enrollment,
)
from apps.lesson.models import Lesson
from apps.home.grading import grade_identifier
from apps.home.services import get_students_for_role
from apps.lesson.services import get_cached_grades_bulk
from core.permissions import can_access_student, IsPsychologist, CanModifyStudent
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
        return Student.objects.select_related('user').prefetch_related('parent__user')

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if not can_access_student(request.user, obj):
            self.permission_denied(request, message=(
                NO_ACCESS_STUDENT
            ))


class StudentProfileUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated,  CanModifyStudent]

    def patch(self, request, pk):
        # get_object_or_404 + an explicit object-permission check: this is a plain
        # APIView, so DRF never calls check_object_permissions() for us and
        # CanModifyStudent (which only defines has_object_permission) would
        # otherwise never run — letting any authenticated user edit any student.
        student = get_object_or_404(
            Student.objects.select_related('user'), pk=pk
        )
        self.check_object_permissions(request, student)

        serializer = StudentProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = student.user
        for field in ('email', 'first_name', 'last_name', 'phone_number', 'date_of_birth', 'address'):
            if field in data:
                setattr(user, field, data[field])
        user.save()

        # Each of the three lookups below used to `except DoesNotExist: pass`,
        # which returned 200 with the change silently discarded — indistinguishable
        # from success to the client. Once scoping is enforced they would swallow a
        # *cross-school* id the same way, so a school-A admin could send school B's
        # class_group and be told it worked. A supplied id that does not resolve is
        # a validation error.
        if 'school_group' in data and data['school_group']:
            from apps.authentication.models import SchoolGroup
            try:
                student.school_group = SchoolGroup.objects.get(id=data['school_group'])
            except SchoolGroup.DoesNotExist:
                raise ValidationError(
                    {'school_group': [f"Invalid pk \"{data['school_group']}\" - object does not exist."]}
                )

        if 'medical_features' in data:
            student.medical_features = data['medical_features']

        if 'academic_year' in data and data['academic_year']:
            try:
                student.academic_year = AcademicYear.objects.get(id=data['academic_year'])
            except AcademicYear.DoesNotExist:
                raise ValidationError(
                    {'academic_year': [f"Invalid pk \"{data['academic_year']}\" - object does not exist."]}
                )

        if 'class_group' in data and data['class_group']:
            try:
                class_group = ClassGroup.objects.get(id=data['class_group'])
            except ClassGroup.DoesNotExist:
                raise ValidationError(
                    {'class_group': [f"Invalid pk \"{data['class_group']}\" - object does not exist."]}
                )
            try:
                academic_year = (
                    student.academic_year
                    or AcademicYear.objects.filter(is_active=True).first()
                )
                if academic_year:
                    Enrollment.enroll_student(student, class_group, academic_year)
            except DjangoValidationError as exc:
                return Response(
                    {'detail': '; '.join(exc.messages)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        student.save()
        return Response(StudentDetailSerializer(student).data)


# ── Psychological States ──

class PsychologicalStateCreateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor | IsPsychologist]

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

        # PsychologicalStateTemplates is a tenant root with a NOT NULL school and
        # no parent to derive one from, so it has to be supplied here. The state
        # is about the student, so the student's school owns the template; the
        # actor's school is the fallback for the (data-defect) case of a student
        # without one. `name` alone still gates the lookup because the column is
        # globally unique until Phase 6 relaxes it to unique(school, name).
        if not PsychologicalStateTemplates.objects.filter(name=data['state_name']).exists():
            PsychologicalStateTemplates.objects.create(
                name=data['state_name'],
                comment=data.get('comment', ''),
                school_id=student.user.school_id or request.user.school_id,
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
    serializer_class = PsychologicalStateTemplateSerializer
    # CanAccessStudent only defines has_object_permission, which a ListAPIView
    # never invokes — it was a no-op here. These templates populate the
    # psychological-state creation form, so they match that view's audience.
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor | IsPsychologist]
    pagination_class = None

    def get_queryset(self):
        # Resolved per request, not at import: a class-body queryset
        # would bake the school scope when the module loads.
        return PsychologicalStateTemplates.objects.all()


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
            class_group__academic_year=enrollment.academic_year,
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
            offering__class_group__academic_year=enrollment.academic_year,
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
            enrollments__class_group__academic_year=enrollment.academic_year,
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
            class_group__academic_year=enrollment.academic_year,
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
