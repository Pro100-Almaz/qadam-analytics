"""
Homework <-> SubjectAssignment mirror (spec 0005).

Every Homework has exactly one SubjectAssignment of category `homework` whose
`detail_id` is the homework's pk, and every HomeworkGrade has a SubjectGrade on
that assignment for the same student. Either side may be written; the other
follows.

The model save()/delete() overrides call in here — deliberately not signals —
and every write made from here passes `sync=False` so it does not echo back.
Lookups use `_base_manager`: the counterpart is the same school by
construction, and this runs outside request scope too (admin actions,
TeachingAssignment.delete, the sync_homework_assignments command).

Field map:

    Homework.description  <-> SubjectAssignment.title
    Homework.max_grade    <-> SubjectAssignment.max_grade
    Homework.due_date     <-> SubjectAssignment.date
    Homework.is_active    <-> SubjectAssignment.is_active
    Homework.offering      -> SubjectAssignment.offering (fixed after creation)

    HomeworkGrade.grade / comments <-> SubjectGrade.grade / comments,
    matched on (homework <-> assignment.detail_id, student).

When the two disagree and nobody says which is right — the sync command's
`--fix` — Homework is the source of truth: it is the richer record, and the
one the homework endpoints were writing before the mirror existed.
"""

from dataclasses import dataclass

from django.db import transaction

from apps.home.models import AssignmentCategory, SubjectAssignment, SubjectGrade
from apps.lesson.models import Homework, HomeworkGrade


def homework_category():
    """The `homework` category row. Created if missing, so it cannot be lost."""
    category, _ = AssignmentCategory.objects.get_or_create(
        code=AssignmentCategory.HOMEWORK, defaults={'name': 'Homework'},
    )
    return category


def mirror_of(homework_id):
    """The SubjectAssignment mirroring this homework, or None."""
    return SubjectAssignment._base_manager.filter(
        category__code=AssignmentCategory.HOMEWORK, detail_id=homework_id,
    ).first()


# ── Assignment level ──

def _assignment_fields(homework):
    return {
        'offering_id': homework.offering_id,
        'title': homework.description,
        'max_grade': homework.max_grade,
        'date': homework.due_date,
        'is_active': homework.is_active,
    }


def assignment_from_homework(homework):
    """Create or update the mirror of `homework`. Returns the assignment."""
    assignment = mirror_of(homework.pk)
    if assignment is None:
        assignment = SubjectAssignment(
            category=homework_category(), detail_id=homework.pk,
        )
    for field, value in _assignment_fields(homework).items():
        setattr(assignment, field, value)
    assignment.save(sync=False)
    return assignment


def homework_from_assignment(assignment):
    """Copy an edited homework-category assignment onto its Homework."""
    homework = Homework._base_manager.get(pk=assignment.detail_id)
    homework.description = assignment.title
    homework.max_grade = assignment.max_grade
    homework.due_date = assignment.date
    homework.is_active = assignment.is_active
    homework.save(sync=False)
    return homework


def delete_assignment(homework_id):
    """Drop the mirror of a homework being deleted; its grades cascade."""
    for assignment in SubjectAssignment._base_manager.filter(
        category__code=AssignmentCategory.HOMEWORK, detail_id=homework_id,
    ):
        assignment.delete(sync=False)


def delete_homework(homework_id):
    """Drop the Homework behind a deleted assignment; grades and files go too."""
    homework = Homework._base_manager.filter(pk=homework_id).first()
    if homework is not None:
        homework.delete(sync=False)


def create_homework_with_assignment(
    *, offering, teaching_assignment, title, max_grade, date, is_active=True,
):
    """
    The POST subject-assignments/ path for category `homework`: the Homework
    is created first, and its save() creates the mirror, which is returned.
    """
    with transaction.atomic():
        homework = Homework(
            offering=offering,
            teaching_assignment=teaching_assignment,
            description=title,
            max_grade=max_grade,
            due_date=date,
            is_active=is_active,
        )
        homework.save()
        return mirror_of(homework.pk)


def assignments_from_homeworks(homeworks):
    """Mirror rows that were written without save(), e.g. by bulk_create."""
    with transaction.atomic():
        return [assignment_from_homework(homework) for homework in homeworks]


# ── Grade level ──

def subject_grade_from_homework_grade(homework_grade):
    assignment = mirror_of(homework_grade.homework_id)
    if assignment is None:
        assignment = assignment_from_homework(homework_grade.homework)
    subject_grade = SubjectGrade._base_manager.filter(
        assignment=assignment, student_id=homework_grade.student_id,
    ).first() or SubjectGrade(
        assignment=assignment, student_id=homework_grade.student_id,
    )
    subject_grade.grade = homework_grade.grade
    subject_grade.comments = homework_grade.comments
    subject_grade.save(sync=False)
    return subject_grade


def homework_grade_from_subject_grade(subject_grade):
    homework_id = subject_grade.assignment.detail_id
    homework_grade = HomeworkGrade._base_manager.filter(
        homework_id=homework_id, student_id=subject_grade.student_id,
    ).first() or HomeworkGrade(
        homework_id=homework_id, student_id=subject_grade.student_id,
    )
    homework_grade.grade = subject_grade.grade
    homework_grade.comments = subject_grade.comments
    homework_grade.save(sync=False)
    return homework_grade


def delete_subject_grade(homework_id, student_id):
    # Queryset delete: SubjectGrade.delete() would sync straight back.
    SubjectGrade._base_manager.filter(
        assignment__category__code=AssignmentCategory.HOMEWORK,
        assignment__detail_id=homework_id,
        student_id=student_id,
    ).delete()


def delete_homework_grade(homework_id, student_id):
    HomeworkGrade._base_manager.filter(
        homework_id=homework_id, student_id=student_id,
    ).delete()


# ── Drift report (sync_homework_assignments) ──

@dataclass(frozen=True)
class Drift:
    kind: str
    detail: str


def find_drift():
    """
    Every place where the two sides disagree, as a list of Drift.

    Covers writes the hooks cannot see: QuerySet.update()/delete(), cascades
    from rows other than the ones overridden, raw SQL.
    """
    problems = []
    homeworks = {hw.pk: hw for hw in Homework._base_manager.all()}
    mirrors = {}
    for assignment in SubjectAssignment._base_manager.filter(
        category__code=AssignmentCategory.HOMEWORK,
    ):
        mirrors[assignment.detail_id] = assignment

    for homework_id, assignment in mirrors.items():
        if homework_id not in homeworks:
            problems.append(Drift(
                'orphan_assignment',
                f'SubjectAssignment #{assignment.pk} points at missing Homework #{homework_id}',
            ))

    for homework_id, homework in homeworks.items():
        assignment = mirrors.get(homework_id)
        if assignment is None:
            problems.append(Drift(
                'missing_assignment', f'Homework #{homework_id} has no SubjectAssignment',
            ))
            continue
        for field, expected in _assignment_fields(homework).items():
            actual = getattr(assignment, field)
            if actual != expected:
                problems.append(Drift(
                    'assignment_drift',
                    f'Homework #{homework_id} / SubjectAssignment #{assignment.pk}: '
                    f'{field} is {actual!r}, expected {expected!r}',
                ))

    subject_grades = {
        (g.assignment.detail_id, g.student_id): g
        for g in SubjectGrade._base_manager.select_related('assignment').filter(
            assignment__category__code=AssignmentCategory.HOMEWORK,
        )
    }
    homework_grades = {
        (g.homework_id, g.student_id): g for g in HomeworkGrade._base_manager.all()
    }
    for key, homework_grade in homework_grades.items():
        subject_grade = subject_grades.get(key)
        if subject_grade is None:
            problems.append(Drift(
                'missing_subject_grade',
                f'HomeworkGrade #{homework_grade.pk} has no SubjectGrade',
            ))
        elif (subject_grade.grade, subject_grade.comments) != (
            homework_grade.grade, homework_grade.comments,
        ):
            problems.append(Drift(
                'grade_drift',
                f'HomeworkGrade #{homework_grade.pk} / SubjectGrade #{subject_grade.pk} differ',
            ))
    for key, subject_grade in subject_grades.items():
        if key not in homework_grades and key[0] in homeworks:
            problems.append(Drift(
                'orphan_subject_grade',
                f'SubjectGrade #{subject_grade.pk} has no HomeworkGrade',
            ))
    return problems


def fix_drift():
    """Make the mirror match Homework again. Returns the drift found before fixing."""
    problems = find_drift()
    if not problems:
        return problems

    with transaction.atomic():
        homework_ids = set(Homework._base_manager.values_list('pk', flat=True))
        for assignment in SubjectAssignment._base_manager.filter(
            category__code=AssignmentCategory.HOMEWORK,
        ).exclude(detail_id__in=homework_ids):
            assignment.delete(sync=False)

        for homework in Homework._base_manager.all():
            assignment_from_homework(homework)

        homework_grade_keys = set()
        for homework_grade in HomeworkGrade._base_manager.select_related('homework'):
            homework_grade_keys.add((homework_grade.homework_id, homework_grade.student_id))
            subject_grade_from_homework_grade(homework_grade)

        for subject_grade in SubjectGrade._base_manager.select_related('assignment').filter(
            assignment__category__code=AssignmentCategory.HOMEWORK,
        ):
            key = (subject_grade.assignment.detail_id, subject_grade.student_id)
            if key not in homework_grade_keys:
                subject_grade.delete(sync=False)
    return problems
