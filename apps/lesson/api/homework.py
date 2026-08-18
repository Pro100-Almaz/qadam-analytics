"""
CRUD endpoints for homework and homework grades.

Read access to homework:
- Admin / Principal / Supervisor — every homework in the school, drafts
                   included. Read only: they never write homework or grades.
- Psychologist   — the same read-only view, matching their blanket read access
                   to grades.
- Teacher        — the homework of every offering they are assigned to. A
                   subject offering can carry several teachers, so the boundary
                   is the offering, not the person who typed the task in.
- Homeroom teacher — additionally the published homework of their own class,
                   across every subject taught to it. That extra reach has its
                   own endpoint (teachers/my-class/homeworks/): their own list
                   (teachers/<id>/homeworks/) stays the homework they may
                   actually write to.
- Student        — the published homework of the subjects taught to the class
                   they are enrolled in, filterable by subject.
- Parent         — the same, for the classes their children are enrolled in.
Nobody else sees homework at all, and drafts (is_active=False) never leave the
offering that owns them.

Read access to grades:
- The student themselves, their parents, teachers of the offering, their
  homeroom teacher, psychologists, and Admin / Principal / Supervisor.

Write access — homework and grades alike:
- Only a teacher assigned to the offering (TeachingAssignment). Admin roles are
  deliberately *not* allowed to write; they read the whole school instead. A
  single POST can target many offerings at once, and the caller must teach
  every one of them.
"""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Parent, Student, Teacher
from apps.home.models import Enrollment, TeachingAssignment
from apps.lesson.models import Homework, HomeworkGrade
from apps.lesson.services import attach_files_to_homeworks
from core.error_messages import NO_PERMISSION, OWN_OFFERINGS_ONLY
from core.permissions import (
    IsTeacherRole,
    is_admin_role,
    is_teacher_role,
    can_access_student,
    teacher_homeroom_class_group_ids,
)

from apps.lesson.api.serializers import (
    HomeworkCreateSerializer,
    HomeworkGradeSerializer,
    HomeworkGradeWriteSerializer,
    HomeworkSerializer,
    HomeworkWriteSerializer,
    StudentHomeworkSerializer,
)


class HomeworkPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


# ── Queryset scoping ──

def enrolled_offering_query(students):
    """
    Q matching homework whose offering is taught to a class one of `students` is
    actively enrolled in, within that same academic year.

    Returns None when there is no active enrollment at all: an empty Q would
    filter on nothing and hand back the whole table, so callers turn None into
    an empty queryset instead.
    """
    pairs = Enrollment.objects.filter(
        student__in=students, status='active',
    ).values_list('class_group_id', 'academic_year_id').distinct()

    query = Q()
    for class_group_id, academic_year_id in pairs:
        query |= Q(
            offering__class_group_id=class_group_id,
            offering__academic_year_id=academic_year_id,
        )
    return query or None


def teacher_offering_ids(teacher):
    """Ids of every offering this teacher is assigned to, in any role."""
    return TeachingAssignment.objects.filter(
        teacher=teacher,
    ).values_list('offering_id', flat=True)


def homework_queryset(user):
    """
    Homework visible to the requesting user — see the module docstring for the
    full matrix.

    Drafts are the sharp edge: they are readable inside their own offering (and
    by admin roles) and nowhere else, so a homeroom teacher, a student or a
    parent only ever meets a task once its teacher has published it.
    """
    qs = Homework.objects.select_related(
        'offering', 'offering__subject',
        'offering__class_group', 'offering__class_group__grade_level',
        'offering__academic_year',
        'teaching_assignment', 'teaching_assignment__teacher',
        'teaching_assignment__teacher__user',
    ).prefetch_related('attachments')

    if is_admin_role(user) or user.is_psychologist():
        return qs

    if is_teacher_role(user):
        teacher = Teacher.objects.filter(user=user).first()
        if teacher is None:
            return qs.none()

        return qs.filter(
            Q(offering_id__in=teacher_offering_ids(teacher))
            | Q(
                offering__class_group_id__in=teacher_homeroom_class_group_ids(teacher),
                is_active=True,
            )
        ).distinct()

    if user.is_student():
        student = Student.objects.filter(user=user).first()
        if student is None:
            return qs.none()
        query = enrolled_offering_query([student])
        return qs.filter(query, is_active=True) if query else qs.none()

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        query = enrolled_offering_query(parent.students.all())
        return qs.filter(query, is_active=True) if query else qs.none()

    return qs.none()


def homeroom_homework_queryset(user):
    """
    Published homework of the classes this user is homeroom teacher of, across
    every subject taught to them.

    Empty for anyone without a homeroom assignment — including admin roles,
    who reach the same rows through teachers/<id>/homeworks/ instead.
    """
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return Homework.objects.none()

    class_group_ids = teacher_homeroom_class_group_ids(teacher)
    if not class_group_ids:
        return Homework.objects.none()

    return homework_queryset(user).filter(
        offering__class_group_id__in=class_group_ids, is_active=True,
    )


def grade_queryset(user):
    """
    Homework grades visible to the requesting user.

    Students see their own rows, parents their children's, teachers the
    offerings they teach plus anything belonging to their homeroom class, and
    psychologists / admin roles see everything.
    """
    qs = HomeworkGrade.objects.select_related(
        'student', 'student__user', 'homework', 'homework__offering',
        'homework__offering__subject', 'homework__offering__class_group',
        'homework__teaching_assignment',
    )

    if is_admin_role(user) or user.is_psychologist():
        return qs

    if is_teacher_role(user):
        teacher = Teacher.objects.filter(user=user).first()
        if teacher is None:
            return qs.none()

        homeroom_ids = teacher_homeroom_class_group_ids(teacher)

        return qs.filter(
            Q(homework__offering_id__in=teacher_offering_ids(teacher))
            | Q(
                student__enrollments__class_group_id__in=homeroom_ids,
                student__enrollments__status='active',
            )
        ).distinct()

    if user.is_student():
        return qs.filter(student__user=user)

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        return qs.filter(student__in=parent.students.all())

    return qs.none()


# ── Write permissions ──

def teacher_assignment_for(user, offering):
    """The requesting user's own TeachingAssignment for an offering, or None."""
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return None
    return TeachingAssignment.objects.filter(
        offering=offering, teacher=teacher,
    ).first()


def can_manage_homework(user, homework):
    """
    Whether the user may edit, delete or grade this homework.

    Homework belongs to its offering rather than to one person: an offering can
    carry several teachers, and any of them — primary, assistant, substitute —
    may work on its tasks, including ones a colleague set. Admin roles are
    excluded on purpose; their reach is read-only.
    """
    return teacher_assignment_for(user, homework.offering) is not None


def _apply_homework_filters(qs, params):
    if params.get('offering'):
        qs = qs.filter(offering_id=params['offering'])
    if params.get('class_group'):
        qs = qs.filter(offering__class_group_id=params['class_group'])
    if params.get('subject'):
        qs = qs.filter(offering__subject_id=params['subject'])
    if params.get('teacher'):
        qs = qs.filter(teaching_assignment__teacher_id=params['teacher'])
    if params.get('academic_year'):
        qs = qs.filter(offering__academic_year_id=params['academic_year'])
    if params.get('is_active') in ('true', 'false'):
        qs = qs.filter(is_active=params['is_active'] == 'true')
    if params.get('due_from'):
        qs = qs.filter(due_date__gte=params['due_from'])
    if params.get('due_to'):
        qs = qs.filter(due_date__lte=params['due_to'])
    return qs


# ── Homework ──

class HomeworkCreateAPIView(APIView):
    """
    POST homeworks/  — create the same homework in one or more offerings

    Listing lives on the per-role endpoints instead: teachers/<id>/homeworks/,
    teachers/my-class/homeworks/ and students/<id>/homeworks/.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(
        request=HomeworkCreateSerializer,
        responses={201: HomeworkSerializer(many=True)},
        description=(
            'Creates one Homework per offering. The caller must be an assigned '
            'teacher of every offering in the list, otherwise nothing is created. '
            'Send as multipart/form-data to attach files: each file in '
            '`attachments` is copied onto every offering in the batch.'
        ),
    )
    def post(self, request):
        serializer = HomeworkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        offerings = data['offerings']
        files = data.get('attachments') or []

        # Resolve the caller's assignment for each target before writing
        # anything — the whole batch fails if one offering is not theirs.
        assignments = {}
        forbidden = []
        for offering in offerings:
            assignment = teacher_assignment_for(request.user, offering)
            if assignment is None:
                forbidden.append(offering.pk)
            else:
                assignments[offering.pk] = assignment

        if forbidden:
            return Response(
                {'detail': OWN_OFFERINGS_ONLY, 'offerings': forbidden},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            created = Homework.objects.bulk_create([
                Homework(
                    offering=offering,
                    teaching_assignment=assignments[offering.pk],
                    description=data['description'],
                    max_grade=data['max_grade'],
                    due_date=data['due_date'],
                    is_active=data['is_active'],
                )
                for offering in offerings
            ])

            # Same files, one stored copy per class, so the batch stays atomic.
            attach_files_to_homeworks(created, files, request.user)

        rows = homework_queryset(request.user).filter(
            pk__in=[homework.pk for homework in created]
        )
        return Response(
            HomeworkSerializer(rows, many=True, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class HomeworkDetailAPIView(APIView):
    """
    GET    homeworks/<pk>/  — single homework
    PUT    homeworks/<pk>/  — replace description / max_grade / due_date / is_active
    DELETE homeworks/<pk>/  — delete homework (cascades to its grades and files)

    Attachments ride along on PUT: `attachments` adds files (multipart),
    `remove_attachments` deletes them by id. Both are optional, and leaving them
    out leaves the existing files alone.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherRole()]

    @extend_schema(responses=HomeworkSerializer)
    def get(self, request, pk):
        homework = get_object_or_404(homework_queryset(request.user), pk=pk)
        return Response(
            HomeworkSerializer(homework, context={'request': request}).data
        )

    @extend_schema(request=HomeworkWriteSerializer, responses=HomeworkSerializer)
    def put(self, request, pk):
        homework = self._get_writable(request, pk)
        if isinstance(homework, Response):
            return homework

        serializer = HomeworkWriteSerializer(
            homework, data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Re-read through the scoped queryset so the response carries the
        # prefetched attachments the edit just changed.
        homework = get_object_or_404(homework_queryset(request.user), pk=pk)
        return Response(
            HomeworkSerializer(homework, context={'request': request}).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        homework = self._get_writable(request, pk)
        if isinstance(homework, Response):
            return homework

        with transaction.atomic():
            # The attachment rows cascade with the homework, but the stored
            # files do not — drop them first so nothing is orphaned on disk.
            for attachment in homework.attachments.all():
                attachment.file.delete(save=False)
            homework.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, pk):
        homework = get_object_or_404(
            Homework.objects.select_related('offering', 'teaching_assignment'),
            pk=pk,
        )
        if not can_manage_homework(request.user, homework):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )
        return homework


# ── Homework grades ──

class HomeworkGradeListCreateAPIView(APIView):
    """
    GET  homeworks/<homework_id>/grades/  — grades the user is allowed to see
    POST homeworks/<homework_id>/grades/  — grade one student

    The list is scoped per role: a student gets back their own row only, a
    parent their children's, a teacher the class they teach. Grading itself is
    a teacher's job — admin roles and psychologists read these rows, never
    write them.
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherRole()]
        return [IsAuthenticated()]

    @extend_schema(
        responses=HomeworkGradeSerializer(many=True),
        parameters=[
            OpenApiParameter('student', int, description='Student profile id.'),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, homework_id):
        homework = get_object_or_404(homework_queryset(request.user), pk=homework_id)

        rows = grade_queryset(request.user).filter(homework=homework)
        if request.query_params.get('student'):
            rows = rows.filter(student_id=request.query_params['student'])
        rows = rows.order_by(
            'student__user__last_name', 'student__user__first_name', 'id',
        )

        paginator = HomeworkPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = HomeworkGradeSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=HomeworkGradeWriteSerializer,
        responses={201: HomeworkGradeSerializer},
    )
    def post(self, request, homework_id):
        homework = get_object_or_404(
            Homework.objects.select_related('offering'), pk=homework_id,
        )
        if not can_manage_homework(request.user, homework):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )

        serializer = HomeworkGradeWriteSerializer(
            data=request.data, context={'request': request, 'homework': homework},
        )
        serializer.is_valid(raise_exception=True)
        grade = serializer.save(homework=homework)

        return Response(
            HomeworkGradeSerializer(grade, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class HomeworkGradeDetailAPIView(APIView):
    """
    PATCH  homework-grades/<pk>/  — change the grade
    DELETE homework-grades/<pk>/  — remove the grade

    Both are limited to the teachers of the offering the homework belongs to;
    the grade itself is read back through the list on
    homeworks/<homework_id>/grades/.
    """
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(request=HomeworkGradeWriteSerializer, responses=HomeworkGradeSerializer)
    def patch(self, request, pk):
        grade = self._get_writable(request, pk)
        if isinstance(grade, Response):
            return grade

        serializer = HomeworkGradeWriteSerializer(
            grade,
            data=request.data,
            partial=True,
            context={'request': request, 'homework': grade.homework},
        )
        serializer.is_valid(raise_exception=True)
        grade = serializer.save()

        return Response(
            HomeworkGradeSerializer(grade, context={'request': request}).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        grade = self._get_writable(request, pk)
        if isinstance(grade, Response):
            return grade

        grade.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, pk):
        grade = get_object_or_404(
            HomeworkGrade.objects.select_related('homework', 'homework__offering'),
            pk=pk,
        )
        if not can_manage_homework(request.user, grade.homework):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )
        return grade


class HomeroomHomeworkListAPIView(APIView):
    """
    GET teachers/my-class/homeworks/ — the published homework of the caller's
    own homeroom class, across every subject taught to it.

    Read-only, and read-only by construction rather than by a flag: writing to a
    homework still needs a TeachingAssignment on its offering, so a homeroom
    teacher editing a colleague's task is the same 403 it has always been. Rows
    the caller does teach show up here too — it is their class's homework list,
    not a list of other people's — and those they can edit through the normal
    endpoints.

    Drafts stay out: an unpublished task belongs to its offering alone. A
    teacher with no homeroom class gets an empty list rather than an error.
    """
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(
        responses=HomeworkSerializer(many=True),
        description=(
            'Published homework of the classes the caller is homeroom teacher '
            'of. Same payload as GET /homeworks/. Empty when the caller has no '
            'homeroom assignment for the active academic year.'
        ),
        parameters=[
            OpenApiParameter('offering', int),
            OpenApiParameter(
                'class_group', int,
                description='Narrow to one class, for a teacher who is homeroom '
                            'teacher of several.',
            ),
            OpenApiParameter('subject', int, description='Subject id.'),
            OpenApiParameter('teacher', int, description='Teacher profile id.'),
            OpenApiParameter('academic_year', int),
            OpenApiParameter('due_from', OpenApiTypes.DATE),
            OpenApiParameter('due_to', OpenApiTypes.DATE),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request):
        rows = _apply_homework_filters(
            homeroom_homework_queryset(request.user), request.query_params,
        ).order_by('-due_date', '-id')

        paginator = HomeworkPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = HomeworkSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)


class TeacherHomeworkListAPIView(APIView):
    """
    GET teachers/<teacher_id>/homeworks/ — homework set by one teacher.

    A teacher may only ask for their own list — a colleague's id is a 403, even
    for a colleague they share an offering with. Admin roles may look at any
    teacher's list, and students and parents get that teacher's published
    homework narrowed to their own classes by homework_queryset().
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=HomeworkSerializer(many=True),
        parameters=[
            OpenApiParameter('offering', int),
            OpenApiParameter('class_group', int),
            OpenApiParameter('subject', int),
            OpenApiParameter('academic_year', int),
            OpenApiParameter('is_active', bool),
            OpenApiParameter('due_from', OpenApiTypes.DATE),
            OpenApiParameter('due_to', OpenApiTypes.DATE),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, teacher_id):
        teacher = get_object_or_404(
            Teacher.objects.select_related('user'), pk=teacher_id,
        )

        # Teachers are pinned to their own list; admin roles are not.
        if not is_admin_role(request.user) and is_teacher_role(request.user):
            if teacher.user_id != request.user.id:
                return Response(
                    {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
                )

        rows = homework_queryset(request.user).filter(
            teaching_assignment__teacher=teacher,
        )
        rows = _apply_homework_filters(rows, request.query_params).order_by(
            '-due_date', '-id',
        )

        paginator = HomeworkPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = HomeworkSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)


class StudentHomeworkListAPIView(APIView):
    """
    GET students/<student_id>/homeworks/ — the homework assigned to one student,
    across every subject taught to the class they are enrolled in.

    Each row carries that student's own grade in `student_grade` (null when
    ungraded, and also null when the caller may not see this student's grades —
    homework itself is readable more widely than grades are).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentHomeworkSerializer(many=True),
        parameters=[
            OpenApiParameter('subject', int),
            OpenApiParameter('offering', int),
            OpenApiParameter('academic_year', int),
            OpenApiParameter('is_active', bool),
            OpenApiParameter('due_from', OpenApiTypes.DATE),
            OpenApiParameter('due_to', OpenApiTypes.DATE),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, student_id):
        student = get_object_or_404(
            Student.objects.select_related('user'), pk=student_id,
        )
        if not can_access_student(request.user, student):
            return Response({'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN)

        rows = self._student_homework(request.user, student)
        rows = _apply_homework_filters(rows, request.query_params).order_by(
            '-due_date', '-id',
        )

        paginator = HomeworkPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = StudentHomeworkSerializer(
            page,
            many=True,
            context={
                'request': request,
                'grade_map': self._grade_map(request.user, student, page),
            },
        )
        return paginator.get_paginated_response(serializer.data)

    @staticmethod
    def _student_homework(user, student):
        """
        Homework belongs to the student when its offering is taught to a class
        they are actively enrolled in, for that same academic year. A student
        with no active enrollment simply has no homework.
        """
        qs = homework_queryset(user)
        query = enrolled_offering_query([student])
        return qs.filter(query) if query else qs.none()

    @staticmethod
    def _grade_map(user, student, homeworks):
        """
        {homework_id: HomeworkGrade} for the rows on this page, honouring the
        caller's grade permissions — one query, no N+1.
        """
        grades = grade_queryset(user).filter(
            student=student,
            homework_id__in=[homework.pk for homework in homeworks],
        )
        return {grade.homework_id: grade for grade in grades}
