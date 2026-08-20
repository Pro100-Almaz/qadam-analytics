"""
CRUD endpoints for quarter grades.

A QuarterGrade is the single mark a student ends a quarter with in one subject
— the 2–5 that goes on the report card. It hangs off a SubjectOffering ("Math
for 7A in 2025/2026") and a quarter, one row per student per subject per
quarter, and it is entered by hand: nothing here derives it from the
assignment grades underneath.

Write access:
- Only a teacher assigned to the offering (TeachingAssignment), and only for
  students actively enrolled in that offering's class group for that offering's
  academic year. As with assignments, the boundary is the offering rather than
  the person who typed the row in, so co-teachers can fix each other's marks.
- Admin roles are deliberately not allowed to write; they read the whole
  school instead.

Read access:
- Admin / Principal / Supervisor and Psychologist — everything, school-wide.
- Teacher        — the offerings they teach, and nothing else.
- Homeroom teacher — their own class has its own endpoint,
                   teachers/my-class/quarter-grades/, which spans every subject
                   taught to that class rather than only the ones they teach.
- Student        — their own marks.
- Parent         — their children's.
Nobody else sees any of it.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Parent, Teacher
from apps.home.models import QuarterGrade
from core.error_messages import NO_PERMISSION, OWN_OFFERINGS_ONLY
from core.permissions import (
    IsTeacherRole,
    is_admin_role,
    is_teacher_role,
    teacher_homeroom_class_group_ids,
)

from apps.home.api.serializers import (
    QuarterGradeCreateSerializer,
    QuarterGradeSerializer,
    QuarterGradeWriteSerializer,
)
from apps.home.api.views.assignments import (
    OFFERING_FILTER_PARAMS,
    PAGE_PARAMS,
    apply_offering_filters,
    teacher_assignment_for,
    teacher_offering_ids,
)


class QuarterGradePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


QUARTER_GRADE_SELECT_RELATED = (
    'student', 'student__user',
    'offering', 'offering__subject',
    'offering__class_group', 'offering__class_group__grade_level',
    'offering__academic_year',
)


# ── Queryset scoping ──

def quarter_grade_queryset(user):
    """Quarter grades visible to the requesting user — see the module docstring."""
    qs = QuarterGrade.objects.select_related(*QUARTER_GRADE_SELECT_RELATED)

    if is_admin_role(user) or user.is_psychologist():
        return qs

    if is_teacher_role(user):
        teacher = Teacher.objects.filter(user=user).first()
        if teacher is None:
            return qs.none()
        return qs.filter(offering_id__in=teacher_offering_ids(teacher))

    if user.is_student():
        return qs.filter(student__user=user)

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        return qs.filter(student__in=parent.students.all())

    return qs.none()


def homeroom_quarter_grade_queryset(user):
    """
    Every quarter grade of the students in the caller's own homeroom class,
    across all subjects taught to it — not only the subjects the caller teaches.

    Empty for anyone without a homeroom assignment in the active academic year,
    admin roles included: they reach the same rows through GET quarter-grades/.
    """
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return QuarterGrade.objects.none()

    class_group_ids = teacher_homeroom_class_group_ids(teacher)
    if not class_group_ids:
        return QuarterGrade.objects.none()

    return QuarterGrade.objects.select_related(
        *QUARTER_GRADE_SELECT_RELATED,
    ).filter(
        student__enrollments__class_group_id__in=class_group_ids,
        student__enrollments__status='active',
    ).distinct()


# ── Write permissions ──

def can_manage_quarter_grade(user, quarter_grade):
    """
    Whether the user may edit or delete this quarter grade.

    A quarter grade belongs to its offering rather than to one person: any
    teacher of that offering may correct it. Homeroom teachers who do not teach
    the subject are not included — their homeroom reach is read-only.
    """
    return teacher_assignment_for(user, quarter_grade.offering) is not None


# ── Filters ──

def _apply_quarter_grade_filters(qs, params):
    qs = apply_offering_filters(qs, params)
    if params.get('quarter'):
        qs = qs.filter(quarter=params['quarter'])
    if params.get('student'):
        qs = qs.filter(student_id=params['student'])
    return qs


QUARTER_PARAM = OpenApiParameter('quarter', int, description='Quarter, 1–4.')
STUDENT_PARAM = OpenApiParameter('student', int, description='Student profile id.')

QUARTER_GRADE_FILTER_PARAMS = (
    OFFERING_FILTER_PARAMS + [QUARTER_PARAM, STUDENT_PARAM] + PAGE_PARAMS
)

QUARTER_GRADE_ORDERING = (
    'offering__subject__name', 'quarter',
    'student__user__last_name', 'student__user__first_name', 'id',
)


class QuarterGradeListCreateAPIView(APIView):
    """
    GET  quarter-grades/  — quarter grades the caller is allowed to see
    POST quarter-grades/  — record one in an offering the caller teaches

    This is the endpoint that answers "what did this student finish the quarter
    with": a student calls it bare and gets their own marks, a parent gets their
    children's, a teacher gets the offerings they teach, and admin roles and
    psychologists get the school. Narrow it with `student` or `quarter` when the
    caller can see more than one.
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherRole()]
        return [IsAuthenticated()]

    @extend_schema(
        responses=QuarterGradeSerializer(many=True),
        parameters=QUARTER_GRADE_FILTER_PARAMS,
        description=(
            'Role-scoped list of quarter grades. Teachers get the offerings '
            'they teach, students their own marks, parents their children\'s, '
            'and admin roles and psychologists the whole school. Homeroom '
            'teachers use teachers/my-class/quarter-grades/ for their class.'
        ),
    )
    def get(self, request):
        rows = _apply_quarter_grade_filters(
            quarter_grade_queryset(request.user), request.query_params,
        ).order_by(*QUARTER_GRADE_ORDERING)

        paginator = QuarterGradePagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = QuarterGradeSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=QuarterGradeCreateSerializer,
        responses={201: QuarterGradeSerializer},
        description=(
            'Records a quarter grade. The caller must be an assigned teacher '
            'of the target offering, and the student must be actively enrolled '
            'in that offering\'s class group. One grade per student per subject '
            'per quarter — change an existing one with PATCH '
            'quarter-grades/<pk>/.'
        ),
    )
    def post(self, request):
        serializer = QuarterGradeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        offering = serializer.validated_data['offering']
        if teacher_assignment_for(request.user, offering) is None:
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )

        quarter_grade = serializer.save()
        return Response(
            QuarterGradeSerializer(quarter_grade, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class QuarterGradeDetailAPIView(APIView):
    """
    GET    quarter-grades/<pk>/  — single quarter grade
    PATCH  quarter-grades/<pk>/  — change the mark or the quarter
    DELETE quarter-grades/<pk>/  — remove it

    Writes are limited to the teachers of the offering; reads follow the same
    scoping as GET quarter-grades/.
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherRole()]

    @extend_schema(responses=QuarterGradeSerializer)
    def get(self, request, pk):
        quarter_grade = get_object_or_404(quarter_grade_queryset(request.user), pk=pk)
        return Response(
            QuarterGradeSerializer(quarter_grade, context={'request': request}).data
        )

    @extend_schema(
        request=QuarterGradeWriteSerializer,
        responses=QuarterGradeSerializer,
        description=(
            'Changes the mark or the quarter. The student and the offering are '
            'fixed after creation — moving a row to another student is a delete '
            'plus a create.'
        ),
    )
    def patch(self, request, pk):
        quarter_grade = self._get_writable(request, pk)
        if isinstance(quarter_grade, Response):
            return quarter_grade

        serializer = QuarterGradeWriteSerializer(
            quarter_grade, data=request.data, partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        quarter_grade = serializer.save()

        return Response(
            QuarterGradeSerializer(quarter_grade, context={'request': request}).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        quarter_grade = self._get_writable(request, pk)
        if isinstance(quarter_grade, Response):
            return quarter_grade

        quarter_grade.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, pk):
        quarter_grade = get_object_or_404(
            QuarterGrade.objects.select_related(*QUARTER_GRADE_SELECT_RELATED), pk=pk,
        )
        if not can_manage_quarter_grade(request.user, quarter_grade):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )
        return quarter_grade


class HomeroomQuarterGradeListAPIView(APIView):
    """
    GET teachers/my-class/quarter-grades/ — every quarter grade of the students
    in the caller's own homeroom class, across every subject taught to it.

    Read-only, and read-only by construction rather than by a flag: writing to
    a quarter grade still needs a TeachingAssignment on the offering, so a
    homeroom teacher editing a colleague's mark is the same 403 it has always
    been. A teacher with no homeroom class gets an empty list rather than an
    error.
    """
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(
        responses=QuarterGradeSerializer(many=True),
        parameters=QUARTER_GRADE_FILTER_PARAMS,
        description=(
            'Quarter grades of the classes the caller is homeroom teacher of. '
            'Same payload as GET quarter-grades/. Empty when the caller has no '
            'homeroom assignment for the active academic year.'
        ),
    )
    def get(self, request):
        rows = _apply_quarter_grade_filters(
            homeroom_quarter_grade_queryset(request.user), request.query_params,
        ).order_by(
            'student__user__last_name', 'student__user__first_name',
            'offering__subject__name', 'quarter', 'id',
        )

        paginator = QuarterGradePagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = QuarterGradeSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)
