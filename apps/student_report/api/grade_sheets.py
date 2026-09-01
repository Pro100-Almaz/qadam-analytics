"""
XLSX grade sheet exports.

    GET grade/classgroup/<class_group_id>/?quarter=2[&subject=7][&ordering=student]
    GET grade/student/<student_id>/?quarter=2[&subject=7][&ordering=student]

Both return a real .xlsx workbook, not JSON. Grades come from SubjectGrade
only. `quarter` is required; `subject` narrows the workbook to a single
subject; `ordering` picks the sheet layout and is rejected alongside `subject`,
which would leave a single sheet either way.
"""

import io
import re
import unicodedata
from urllib.parse import quote

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.models import Student
from apps.home.models import AcademicYear, ClassGroup, SubjectOffering
from apps.student_report.permissions import (
    can_read_class_group_sheet,
    can_read_student_sheet,
)
from apps.student_report.services.grade_sheet import (
    GradeSheetError,
    active_students,
    class_group_label,
    collect_grade_sheet,
    student_name,
)
from apps.student_report.services.grade_workbook import build_grade_workbook
from core.error_messages import NO_PERMISSION

XLSX_CONTENT_TYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)

ORDERING_CHOICES = ('subject', 'student')

GRADE_SHEET_PARAMS = [
    OpenApiParameter(
        'quarter', OpenApiTypes.INT, required=True,
        description='Quarter to export, 1-4. Required.',
    ),
    OpenApiParameter(
        'subject', OpenApiTypes.INT,
        description=(
            'Subject id. Narrows the workbook to that subject alone. '
            'Cannot be combined with `ordering`.'
        ),
    ),
    OpenApiParameter(
        'ordering', OpenApiTypes.STR, enum=list(ORDERING_CHOICES),
        description=(
            '"subject" (default) gives one sheet per subject with students as '
            'rows; "student" gives one sheet per student stacking a small '
            'table per subject. Unavailable together with `subject`.'
        ),
    ),
]


# ── Query parameters ──

def _parse_int(params, *names):
    """First of `names` present in the query string, as an int, or None."""
    for name in names:
        raw = params.get(name)
        if raw in (None, ''):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValidationError({name: 'Must be an integer.'})
    return None


def parse_grade_sheet_params(params):
    """Validate quarter / subject / ordering together. Returns a 3-tuple."""
    raw_quarter = params.get('quarter')
    if raw_quarter in (None, ''):
        raise ValidationError({'quarter': 'This query parameter is required.'})
    try:
        quarter = int(raw_quarter)
    except (TypeError, ValueError):
        raise ValidationError({'quarter': 'Must be an integer between 1 and 4.'})
    if quarter not in (1, 2, 3, 4):
        raise ValidationError({'quarter': 'Must be between 1 and 4.'})

    subject_id = _parse_int(params, 'subject', 'subject_id')

    raw_ordering = params.get('ordering')
    if raw_ordering and subject_id is not None:
        raise ValidationError({
            'ordering': (
                '`ordering` cannot be combined with `subject`: a single '
                'subject produces one sheet either way.'
            ),
        })
    ordering = raw_ordering or 'subject'
    if ordering not in ORDERING_CHOICES:
        raise ValidationError({
            'ordering': f'Must be one of: {", ".join(ORDERING_CHOICES)}.',
        })

    return quarter, subject_id, ordering


def resolve_subject(class_group, academic_year, subject_id):
    """Confirm the subject is actually taught to this class group this year."""
    if subject_id is None:
        return None
    offering = SubjectOffering.objects.filter(
        class_group=class_group,
        academic_year=academic_year,
        subject_id=subject_id,
    ).select_related('subject').first()
    if offering is None:
        raise ValidationError({
            'subject': (
                'This subject is not taught to this class group in '
                f'{academic_year}.'
            ),
        })
    return offering.subject


# ── Response ──

def _content_disposition(stem):
    """
    Names the download in both the legacy and RFC 5987 forms.

    Student and class names are routinely Cyrillic, which a bare `filename=`
    cannot carry, so the ASCII form is only a fallback for clients that ignore
    `filename*`.
    """
    ascii_stem = unicodedata.normalize('NFKD', stem).encode('ascii', 'ignore').decode()
    ascii_stem = re.sub(r'[^A-Za-z0-9._-]+', '_', ascii_stem).strip('_') or 'grades'
    return (
        f'attachment; filename="{ascii_stem}.xlsx"; '
        f"filename*=UTF-8''{quote(stem + '.xlsx')}"
    )


def xlsx_response(workbook, stem):
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = _content_disposition(stem)
    return response


def _academic_year_for(class_group):
    year = class_group.academic_year or AcademicYear.objects.filter(is_active=True).first()
    if year is None:
        raise ValidationError({
            'class_group': (
                'This class group has no academic year and no active academic '
                'year is configured.'
            ),
        })
    return year


def _build(class_group, academic_year, quarter, students, subject_id, ordering):
    try:
        data = collect_grade_sheet(
            class_group=class_group,
            academic_year=academic_year,
            quarter=quarter,
            students=students,
            subject_id=subject_id,
        )
    except GradeSheetError as exc:
        raise ValidationError({'quarter': str(exc)})
    return build_grade_workbook(data, ordering=ordering)


# ── Views ──

class ClassGroupGradeSheetView(APIView):
    """GET grade/classgroup/<id>/ — every enrolled student's grades as XLSX."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=GRADE_SHEET_PARAMS,
        responses={(200, XLSX_CONTENT_TYPE): OpenApiTypes.BINARY},
        description=(
            'Grade sheet for a whole class group in one quarter, as an .xlsx '
            'workbook. Readable by the class group\'s homeroom teacher and by '
            'admin roles; passing `subject` also opens it to the teachers of '
            'that subject\'s offering for the class.'
        ),
    )
    def get(self, request, class_group_id):
        class_group = get_object_or_404(
            ClassGroup.objects.select_related('academic_year', 'grade_level'),
            pk=class_group_id,
        )
        quarter, subject_id, ordering = parse_grade_sheet_params(request.query_params)
        academic_year = _academic_year_for(class_group)

        if not can_read_class_group_sheet(
            request.user, class_group, academic_year, subject_id,
        ):
            raise PermissionDenied(NO_PERMISSION)

        subject = resolve_subject(class_group, academic_year, subject_id)
        students = active_students(class_group, academic_year)

        workbook = _build(
            class_group, academic_year, quarter, students, subject_id, ordering,
        )

        stem = f'Grades_{class_group_label(class_group)}'
        if subject is not None:
            stem += f'_{subject.name}'
        return xlsx_response(workbook, f'{stem}_Q{quarter}')


class StudentGradeSheetView(APIView):
    """GET grade/student/<id>/ — one student's grades as XLSX."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=GRADE_SHEET_PARAMS,
        responses={(200, XLSX_CONTENT_TYPE): OpenApiTypes.BINARY},
        description=(
            'Grade sheet for a single student in one quarter, as an .xlsx '
            'workbook. Readable by the student, their parents, their homeroom '
            'teacher and admin roles; passing `subject` also opens it to the '
            'teachers of that subject\'s offering for the student\'s class.'
        ),
    )
    def get(self, request, student_id):
        student = get_object_or_404(
            Student.objects.select_related('user'), pk=student_id,
        )
        quarter, subject_id, ordering = parse_grade_sheet_params(request.query_params)

        enrollment = student.get_current_enrollment()
        class_group = enrollment.class_group if enrollment else None
        academic_year = enrollment.academic_year if enrollment else None

        # Ahead of the enrollment error below, so that an outsider gets a 403
        # rather than learning whether this student is enrolled.
        if not can_read_student_sheet(
            request.user, student, class_group, academic_year, subject_id,
        ):
            raise PermissionDenied(NO_PERMISSION)

        if enrollment is None:
            raise ValidationError({
                'student': (
                    'This student has no active enrollment, so there is no '
                    'class group to report on.'
                ),
            })

        subject = resolve_subject(class_group, academic_year, subject_id)

        workbook = _build(
            class_group, academic_year, quarter, [student], subject_id, ordering,
        )

        stem = f'Grades_{student_name(student)}'
        if subject is not None:
            stem += f'_{subject.name}'
        return xlsx_response(workbook, f'{stem}_Q{quarter}')
