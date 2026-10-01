"""
Quarter grades, managed per offering (spec 0008).

A QuarterGrade is the single mark a student ends a quarter with in one subject
— the 2–5 that goes on the report card. It hangs off a SubjectOffering ("Math
for 7A in 2025/2026") and a quarter, one row per student per subject per
quarter, and it is entered by hand: nothing here derives it from the
assignment grades underneath.

    offerings/<offering_id>/quarter-grades/
        GET     every quarter grade of the offering (?quarter=N narrows it)
        POST    {"quarter": q, "grades": {student_id: grade}}  create
        PATCH   {"quarter": q, "grades": {student_id: grade}}  change
        DELETE  {"quarter": q, "students": [student_id, ...]}  remove

Writes are all-or-nothing: one bad student fails the whole request.

Write access:
- Only a teacher assigned to the offering (TeachingAssignment), in any role
  — co-teachers can fix each other's marks. Nobody else: not admin roles, and
  not the homeroom teacher of the class unless they also teach the subject.
  QuarterGrade is deliberately not registered in the Django admin either.

Read access:
- Any staff member (IsStaffOrAdmin: admin roles, teachers, psychologists),
  for any offering in the school. Students and parents get nothing.
- Homeroom teachers additionally have teachers/my-class/quarter-grades/,
  which spans every subject taught to their class.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Teacher
from apps.home.models import QuarterGrade, SubjectOffering
from core.error_messages import OWN_OFFERINGS_ONLY
from core.permissions import (
    IsStaffOrAdmin,
    IsTeacherRole,
    teacher_homeroom_class_group_ids,
)

from apps.home.api.serializers import (
    QuarterGradeBulkDeleteSerializer,
    QuarterGradeBulkSerializer,
    QuarterGradeSerializer,
)
from apps.home.api.views.assignments import (
    OFFERING_FILTER_PARAMS,
    PAGE_PARAMS,
    apply_offering_filters,
    teacher_assignment_for,
)


class QuarterGradePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


QUARTER_GRADE_SELECT_RELATED = (
    'student', 'student__user',
    'offering', 'offering__subject',
    'offering__class_group', 'offering__class_group__grade_level',
    'offering__class_group__academic_year',
)


# ── Queryset scoping ──

def homeroom_quarter_grade_queryset(user):
    """
    Every quarter grade of the students in the caller's own homeroom class,
    across all subjects taught to it — not only the subjects the caller teaches.

    Empty for anyone without a homeroom assignment in the active academic year,
    admin roles included: they reach the same rows through
    GET offerings/<offering_id>/quarter-grades/.
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

OFFERING_QUARTER_GRADE_ORDERING = (
    'quarter', 'student__user__last_name', 'student__user__first_name', 'id',
)


class OfferingQuarterGradeAPIView(APIView):
    """
    GET / POST / PATCH / DELETE offerings/<offering_id>/quarter-grades/

    See the module docstring for the payloads and who may call what. The
    permission check runs before the payload is validated, so a caller without
    write access gets 403 whatever they send.
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated(), IsStaffOrAdmin()]
        return [IsAuthenticated(), IsTeacherRole()]

    @extend_schema(
        responses=QuarterGradeSerializer(many=True),
        parameters=[QUARTER_PARAM],
        description=(
            'Every quarter grade of the offering, for any staff member. '
            'Students and parents get 403.'
        ),
    )
    def get(self, request, offering_id):
        offering = get_object_or_404(SubjectOffering.objects.all(), pk=offering_id)
        rows = QuarterGrade.objects.select_related(
            *QUARTER_GRADE_SELECT_RELATED,
        ).filter(offering=offering)
        if request.query_params.get('quarter'):
            rows = rows.filter(quarter=request.query_params['quarter'])

        return Response(QuarterGradeSerializer(
            rows.order_by(*OFFERING_QUARTER_GRADE_ORDERING), many=True,
            context={'request': request},
        ).data)

    @extend_schema(
        request=QuarterGradeBulkSerializer,
        responses={201: QuarterGradeSerializer(many=True)},
        description=(
            'Records the quarter grades of several students at once. Fails as '
            'a whole if any student is not enrolled in the class or is already '
            'graded for the quarter — change existing grades with PATCH.'
        ),
    )
    def post(self, request, offering_id):
        offering, refusal = self._get_writable(request, offering_id)
        if refusal:
            return refusal

        data = self._validated(QuarterGradeBulkSerializer, request, offering, 'create')
        with transaction.atomic():
            created = [
                QuarterGrade.objects.create(
                    offering=offering, student_id=student_id,
                    quarter=data['quarter'], grade=grade,
                )
                for student_id, grade in data['grades'].items()
            ]
        return Response(
            self._serialize(request, [row.pk for row in created]),
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=QuarterGradeBulkSerializer,
        responses=QuarterGradeSerializer(many=True),
        description=(
            'Changes the quarter grades of the listed students. Students not '
            'listed are untouched. Fails as a whole if any listed student has '
            'no grade for the quarter yet.'
        ),
    )
    def patch(self, request, offering_id):
        offering, refusal = self._get_writable(request, offering_id)
        if refusal:
            return refusal

        data = self._validated(QuarterGradeBulkSerializer, request, offering, 'update')
        grades = data['grades']
        rows = list(QuarterGrade.objects.filter(
            offering=offering, quarter=data['quarter'], student_id__in=grades,
        ))
        for row in rows:
            row.grade = grades[row.student_id]
        QuarterGrade.objects.bulk_update(rows, ['grade'])

        return Response(self._serialize(request, [row.pk for row in rows]))

    @extend_schema(
        request=QuarterGradeBulkDeleteSerializer,
        responses={204: None},
        description=(
            'Removes the quarter grades of the listed students. Fails as a '
            'whole if any listed student has no grade for the quarter.'
        ),
    )
    def delete(self, request, offering_id):
        offering, refusal = self._get_writable(request, offering_id)
        if refusal:
            return refusal

        data = self._validated(QuarterGradeBulkDeleteSerializer, request, offering)
        QuarterGrade.objects.filter(
            offering=offering, quarter=data['quarter'], student_id__in=data['students'],
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, offering_id):
        """The offering, or a 403 unless the caller teaches it — admin roles included."""
        offering = get_object_or_404(
            SubjectOffering.objects.select_related('class_group'), pk=offering_id,
        )
        if teacher_assignment_for(request.user, offering) is None:
            return offering, Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )
        return offering, None

    @staticmethod
    def _validated(serializer_class, request, offering, mode=None):
        serializer = serializer_class(
            data=request.data, context={'offering': offering, 'mode': mode},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @staticmethod
    def _serialize(request, pks):
        rows = QuarterGrade.objects.select_related(
            *QUARTER_GRADE_SELECT_RELATED,
        ).filter(pk__in=pks).order_by(*OFFERING_QUARTER_GRADE_ORDERING)
        return QuarterGradeSerializer(rows, many=True, context={'request': request}).data


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
            'Same payload as GET offerings/<offering_id>/quarter-grades/. '
            'Empty when the caller has no '
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
