from rest_framework import status
from rest_framework.generics import (
    ListAPIView, RetrieveAPIView, CreateAPIView, DestroyAPIView,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import (
    Student, Teacher, Parent,
    PsychologicalState, PsychologicalStateTemplates,
)
from apps.home.models import (
    AcademicYear, ClassGroup, Subject, SubjectOffering,
    TeachingAssignment, Enrollment,
)
from apps.lesson.models import Lesson
from apps.home.repo.students import calculate_quarter_grade, grade_identifier
from core.permissions import (
    can_access_student, can_access_subject, can_modify_subject,
    is_admin_role, is_teacher_role,
)

from .permissions import (
    IsTeacherAdminOrSupervisor, IsAdminOrSupervisor, IsParent,
    CanAccessStudent, CanModifyStudent, CanAccessSubject, CanModifySubject,
)
from .serializers import (
    AcademicYearSerializer,
    ClassGroupSerializer,
    StudentListSerializer,
    StudentDetailSerializer,
    StudentProfileUpdateSerializer,
    TeacherListSerializer,
    TeacherDetailSerializer,
    TeacherProfileUpdateSerializer,
    SubjectSerializer,
    SubjectCreateSerializer,
    SubjectDetailSerializer,
    SubjectStatusSerializer,
    DashboardStatsSerializer,
    PsychologicalStateCreateSerializer,
    PsychologicalStateTemplateSerializer,
    EnrollmentSerializer,
)


# ── Dashboard ──

class DashboardStatsAPIView(APIView):
    def get(self, request):
        data = {
            'total_students': Student.objects.count(),
            'total_teachers': Teacher.objects.count(),
            'total_classes': ClassGroup.objects.count(),
        }
        return Response(DashboardStatsSerializer(data).data)


# ── Academic Year / Class Group ──

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


# ── Students ──

class StudentListAPIView(ListAPIView):
    serializer_class = StudentListSerializer
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get_queryset(self):
        year_id = self.request.query_params.get('year')
        class_group_id = self.request.query_params.get('class_group')

        if not year_id:
            latest = AcademicYear.objects.order_by('-year').first()
            year_id = latest.id if latest else None

        if not year_id:
            return Student.objects.none()

        enrollments = Enrollment.objects.filter(
            academic_year_id=year_id, status='active'
        ).select_related('student', 'student__user', 'class_group')

        if class_group_id:
            enrollments = enrollments.filter(class_group_id=class_group_id)

        students = []
        for e in enrollments:
            e.student.classroom = e.class_group
            students.append(e.student)
        return students


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
                "Вы не можете просмотреть профиль данного ученика."
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


# ── Teachers ──

class TeacherListAPIView(ListAPIView):
    serializer_class = TeacherListSerializer
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get_queryset(self):
        return Teacher.objects.select_related('user').all()


class TeacherDetailAPIView(RetrieveAPIView):
    serializer_class = TeacherDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'user_id'
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Teacher.objects.select_related('user')


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

        return Teacher.objects.filter(id__in=teacher_ids).select_related('user')


# ── Subjects ──

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
                "You do not have permission to view this subject."
            ))


class SubjectGradesAPIView(APIView):
    """Returns grade data for a subject filtered by quarter."""

    def get(self, request, pk):
        quarter = int(request.query_params.get('quarter', 1))
        subject = Subject.objects.get(pk=pk)

        if not can_access_subject(request.user, subject):
            return Response(
                {'detail': 'You do not have permission to view this subject.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        current_year = AcademicYear.objects.filter(is_active=True).first()
        if not current_year:
            current_year = AcademicYear.objects.order_by('-year').first()

        offerings = list(
            SubjectOffering.objects.filter(
                subject=subject, academic_year=current_year
            ).select_related('class_group')
        ) if current_year else []

        student_ids_seen = set()
        students = []
        for offering in offerings:
            enrollments = Enrollment.objects.filter(
                class_group=offering.class_group,
                academic_year=offering.academic_year,
                status='active',
            ).select_related('student', 'student__user')
            for e in enrollments:
                if e.student.id not in student_ids_seen:
                    student_ids_seen.add(e.student.id)
                    students.append(e.student)

        total_lessons = list(Lesson.objects.filter(offering__in=offerings))
        quarter_lessons = [l for l in total_lessons if l.quarter == quarter]
        quarter_lessons.sort(key=lambda x: x.created_at)

        all_grades_map = Lesson.calculate_grades_bulk(total_lessons, students)

        lesson_avgs = {}
        for lesson in quarter_lessons:
            lesson_avgs[lesson.id] = {}
            for student in students:
                lesson_avgs[lesson.id][student.id] = round(
                    all_grades_map.get((lesson.id, student.id), 0), 1
                )

        student_grades = {}
        total_student_grades = {}

        for student in students:
            total_grade = sum(
                all_grades_map.get((l.id, student.id), 0) for l in total_lessons
            )
            quarter_grade = sum(
                all_grades_map.get((l.id, student.id), 0) for l in quarter_lessons
            )

            avg_quarter = quarter_grade / len(quarter_lessons) if quarter_lessons else 0
            avg_total = total_grade / len(total_lessons) if total_lessons else 0

            student_grades[student.id] = {
                'grade': round(avg_quarter, 1),
                'student_name': student.user.get_full_name(),
                'student_id': student.id,
                'user_id': student.user.id,
            }
            total_student_grades[student.id] = round(avg_total, 1)

        top_grades = sorted(
            student_grades.values(), key=lambda x: x['grade'], reverse=True
        )

        students_count = len(students)
        avg_points = (
            round(sum(s['grade'] for s in student_grades.values()) / len(student_grades), 1)
            if student_grades else 0
        )
        graded = len([g for g in total_student_grades.values() if g > 0])
        completion = round((graded / students_count) * 100, 1) if students_count else 0

        lessons_data = [
            {'id': l.id, 'title': l.title, 'date': l.date, 'order': l.order}
            for l in quarter_lessons
        ]

        return Response({
            'quarter': quarter,
            'students_count': students_count,
            'lessons_count': len(total_lessons),
            'average_subject_points': avg_points,
            'completion_percent': completion,
            'top_grades': top_grades,
            'lessons': lessons_data,
            'lesson_avgs': {
                str(lid): {str(sid): g for sid, g in smap.items()}
                for lid, smap in lesson_avgs.items()
            },
        })


class SubjectStatusAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, pk):
        subject = Subject.objects.get(pk=pk)
        if not can_modify_subject(request.user, subject):
            return Response(
                {'detail': 'You can only modify status of your own subjects.'},
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


# ── Enrollments ──

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


# ── Psychological States ──

class PsychologicalStateCreateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, pk):
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist:
            return Response(
                {'detail': 'Student not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not can_access_student(request.user, student):
            return Response(
                {'detail': 'You do not have access to this student.'},
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


class PsychologicalStateDeleteAPIView(DestroyAPIView):
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get_queryset(self):
        return PsychologicalState.objects.all()

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if obj.student and not can_access_student(request.user, obj.student):
            self.permission_denied(request, message=(
                "You do not have access to this student."
            ))


class PsychologicalStateTemplateListAPIView(ListAPIView):
    queryset = PsychologicalStateTemplates.objects.all()
    serializer_class = PsychologicalStateTemplateSerializer
    pagination_class = None
