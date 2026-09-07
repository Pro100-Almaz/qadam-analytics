"""
Collects the grade data that the XLSX grade sheets are built from.

Everything here reads SubjectGrade / SubjectAssignment and nothing else — the
lesson/topic grading tree is deliberately not consulted.

A SubjectAssignment carries no quarter of its own, only a date, so a quarter is
resolved into the closed date range the AcademicYear records for it
(``q1_start`` … ``q4_end``) and assignments are filtered by that range.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from apps.home.models import (
    Enrollment,
    SubjectAssignment,
    SubjectGrade,
    SubjectOffering,
)


class GradeSheetError(Exception):
    """A request that cannot be satisfied — views turn this into a 400."""


@dataclass(frozen=True)
class GradeColumn:
    """One assignment: a column in `subject` ordering, a column in `student` ordering too."""
    assignment_id: int
    title: str
    date: date
    max_grade: int
    category: str


@dataclass(frozen=True)
class GradeCell:
    grade: Optional[int]
    comment: str


@dataclass(frozen=True)
class StudentRow:
    student_id: int
    name: str


@dataclass
class SubjectBlock:
    subject_id: int
    subject_name: str
    offering_id: int
    columns: list = field(default_factory=list)


@dataclass
class GradeSheetData:
    """Everything one workbook needs, already ordered for rendering."""
    quarter: int
    period_start: date
    period_end: date
    class_group_label: str
    academic_year_label: str
    students: list = field(default_factory=list)
    subjects: list = field(default_factory=list)
    cells: dict = field(default_factory=dict)

    def cell(self, student_id: int, assignment_id: int):
        return self.cells.get((student_id, assignment_id))

    @property
    def widest_subject(self) -> int:
        """Column count of the subject with the most assignments."""
        return max((len(s.columns) for s in self.subjects), default=0)


def quarter_period(academic_year, quarter: int):
    """
    The (start, end) days of a quarter, both inclusive.

    Raises GradeSheetError when the year has no dates configured for it —
    without them there is no way to tell which assignments belong to the
    quarter, and silently returning everything would be worse than a 400.
    """
    start = getattr(academic_year, f'q{quarter}_start', None)
    end = getattr(academic_year, f'q{quarter}_end', None)
    if not start or not end:
        raise GradeSheetError(
            f'Academic year "{academic_year}" has no start/end dates set for '
            f'quarter {quarter}, so its assignments cannot be selected.'
        )
    if start > end:
        raise GradeSheetError(
            f'Academic year "{academic_year}" has quarter {quarter} ending '
            f'before it starts.'
        )
    return start, end


def class_group_label(class_group) -> str:
    return f'{class_group.grade_level}{class_group.letter}'


def student_name(student) -> str:
    return student.user.get_full_name() or student.user.username


def active_students(class_group, academic_year):
    """Students actively enrolled in the class group, ordered by name."""
    enrollments = Enrollment.objects.filter(
        class_group=class_group,
        academic_year=academic_year,
        status='active',
    ).select_related('student', 'student__user').order_by(
        'student__user__last_name',
        'student__user__first_name',
        'student__user__username',
    )
    return [e.student for e in enrollments]


def offerings_for(class_group, academic_year, subject_id=None):
    """The class group's offerings for the year, narrowed to one subject if asked."""
    qs = SubjectOffering.objects.filter(
        class_group=class_group,
        academic_year=academic_year,
    ).select_related('subject')
    if subject_id is not None:
        qs = qs.filter(subject_id=subject_id)
    return list(qs.order_by('subject__name', 'subject_id'))


def collect_grade_sheet(
    *,
    class_group,
    academic_year,
    quarter: int,
    students,
    subject_id=None,
) -> GradeSheetData:
    """
    Build the full grade grid for `students` within one class group and quarter.

    Four queries regardless of how many students or subjects are involved:
    offerings, assignments, grades, and the enrollment lookup the caller
    already did to produce `students`.
    """
    period_start, period_end = quarter_period(academic_year, quarter)

    data = GradeSheetData(
        quarter=quarter,
        period_start=period_start,
        period_end=period_end,
        class_group_label=class_group_label(class_group),
        academic_year_label=str(academic_year),
        students=[
            StudentRow(student_id=s.id, name=student_name(s)) for s in students
        ],
    )

    offerings = offerings_for(class_group, academic_year, subject_id)
    if not offerings:
        return data

    assignments = SubjectAssignment.objects.filter(
        offering__in=offerings,
        date__gte=period_start,
        date__lte=period_end,
    ).order_by('date', 'id')

    columns_by_offering = {offering.id: [] for offering in offerings}
    for assignment in assignments:
        columns_by_offering[assignment.offering_id].append(
            GradeColumn(
                assignment_id=assignment.id,
                title=assignment.title,
                date=assignment.date,
                max_grade=assignment.max_grade,
                category=assignment.category,
            )
        )

    data.subjects = [
        SubjectBlock(
            subject_id=offering.subject_id,
            subject_name=offering.subject.name,
            offering_id=offering.id,
            columns=columns_by_offering[offering.id],
        )
        for offering in offerings
    ]

    student_ids = [s.student_id for s in data.students]
    if not student_ids:
        return data

    grades = SubjectGrade.objects.filter(
        assignment__offering__in=offerings,
        assignment__date__gte=period_start,
        assignment__date__lte=period_end,
        student_id__in=student_ids,
    ).values('student_id', 'assignment_id', 'grade', 'comments')

    data.cells = {
        (g['student_id'], g['assignment_id']): GradeCell(
            grade=g['grade'],
            comment=(g['comments'] or '').strip(),
        )
        for g in grades
    }
    return data
