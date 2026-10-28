"""
Homework <-> SubjectAssignment mirror (spec 0005).

Every Homework has exactly one SubjectAssignment of category `homework` whose
`detail_id` is the homework's pk, and every HomeworkGrade has a SubjectGrade on
that assignment for the same student. Either side may be edited, and grades
created or deleted, from either side; the other follows. Deletion of the
assignment itself is one-way (spec 0007): deleting the Homework removes its
assignment, and the assignment refuses to be deleted on its own.

The model save() overrides call in here — deliberately not signals — and
every write made from here passes `sync=False` so it does not echo back.
Deletes do not come through here: they are soft (spec 0014), and each model's
`soft_delete_extra()` puts its mirror in the same deletion batch, so the pair
is deleted and restored together.

Lookups use `_base_manager` filtered to live rows: the counterpart is the same
school by construction, and this runs outside request scope too (admin
actions, the sync_homework_assignments command). Soft-deleted rows are out of
the mirror entirely — neither side's deleted rows are synced, reported or
repaired.

Field map:

    Homework.description  <-> SubjectAssignment.title
    Homework.max_grade    <-> SubjectAssignment.max_grade
    Homework.due_date     <-> SubjectAssignment.date
    Homework.is_active    <-> SubjectAssignment.is_active
    Homework.offering      -> SubjectAssignment.offering (fixed after creation)
    Homework.due_date      -> SubjectAssignment.quarter, re-derived whenever the
                              date moves; Homework has no quarter of its own, so
                              a quarter set on the assignment stays until then.

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
    return AssignmentCategory.builtin(AssignmentCategory.HOMEWORK)


def _live(model):
    return model._base_manager.filter(is_deleted=False)


def mirror_of(homework_id):
    """The live SubjectAssignment mirroring this homework, or None."""
    return _live(SubjectAssignment).filter(
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
    elif assignment.date != homework.due_date:
        assignment.quarter = None  # save() derives it again from the new date
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


def create_homework_with_assignment(
    *, offering, teaching_assignment, title, max_grade, date, is_active=True,
    quarter=None,
):
    """
    The POST subject-assignments/ path for category `homework`: the Homework
    is created first, and its save() creates the mirror, which is returned.
    `quarter` overrides the one derived from `date`.
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
        assignment = mirror_of(homework.pk)
        if quarter is not None and assignment.quarter != quarter:
            assignment.quarter = quarter
            assignment.save(sync=False)
        return assignment


def assignments_from_homeworks(homeworks):
    """Mirror rows that were written without save(), e.g. by bulk_create."""
    with transaction.atomic():
        return [assignment_from_homework(homework) for homework in homeworks]


# ── Grade level ──

def subject_grade_from_homework_grade(homework_grade):
    assignment = mirror_of(homework_grade.homework_id)
    if assignment is None:
        assignment = assignment_from_homework(homework_grade.homework)
    subject_grade = _live(SubjectGrade).filter(
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
    homework_grade = _live(HomeworkGrade).filter(
        homework_id=homework_id, student_id=subject_grade.student_id,
    ).first() or HomeworkGrade(
        homework_id=homework_id, student_id=subject_grade.student_id,
    )
    homework_grade.grade = subject_grade.grade
    homework_grade.comments = subject_grade.comments
    homework_grade.save(sync=False)
    return homework_grade


# ── Drift report (sync_homework_assignments) ──

@dataclass(frozen=True)
class Drift:
    kind: str
    detail: str


def find_drift():
    """
    Every place where the two sides disagree, as a list of Drift.

    Covers writes the hooks cannot see: QuerySet.update(), raw SQL, and a
    delete made with `sync=False`. Live rows only.
    """
    problems = []
    homeworks = {hw.pk: hw for hw in _live(Homework)}
    mirrors = {}
    for assignment in _live(SubjectAssignment).filter(
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
        for g in _live(SubjectGrade).select_related('assignment').filter(
            assignment__category__code=AssignmentCategory.HOMEWORK,
        )
    }
    homework_grades = {
        (g.homework_id, g.student_id): g for g in _live(HomeworkGrade)
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
        homework_ids = set(_live(Homework).values_list('pk', flat=True))
        for assignment in _live(SubjectAssignment).filter(
            category__code=AssignmentCategory.HOMEWORK,
        ).exclude(detail_id__in=homework_ids):
            assignment.delete(sync=False)

        for homework in _live(Homework):
            assignment_from_homework(homework)

        homework_grade_keys = set()
        for homework_grade in _live(HomeworkGrade).select_related('homework'):
            homework_grade_keys.add((homework_grade.homework_id, homework_grade.student_id))
            subject_grade_from_homework_grade(homework_grade)

        for subject_grade in _live(SubjectGrade).select_related('assignment').filter(
            assignment__category__code=AssignmentCategory.HOMEWORK,
        ):
            key = (subject_grade.assignment.detail_id, subject_grade.student_id)
            if key not in homework_grade_keys:
                subject_grade.delete(sync=False)
    return problems
