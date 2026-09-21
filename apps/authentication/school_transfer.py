"""Whether a user can change school, and what it would leave behind.

`CustomUser.school` looks like an ordinary field, so changing it looks like an
ordinary edit. It is not. Measured on a student with one enrollment and one
grade, changing nothing else:

    Student      A: True  -> A: False  B: True     (follows the user)
    Enrollment   A: True  -> A: True   B: False    (stays behind)
    TopicGrade   A: True  -> A: True   B: False    (stays behind)

Nothing is deleted and the move is exactly reversible, but the person and their
academic record end up in different tenants: school A keeps the history and
loses the student, school B gains the student with no history. Worse, the
profile then fails `Student.SCHOOL_CONSISTENT_FIELDS` on every save, so school B
can see the student and cannot edit them.

So the admin allows the move only for a user with nothing to strand, and
explains the blockers otherwise. That covers the case the capability exists
for — correcting a phase-1 misfile, or a user created in the wrong school — and
refuses the one that quietly breaks data, a real mid-year transfer, which needs
enrollments and marks moved deliberately rather than as a side effect of a
dropdown.

**What decides whether a row follows its person.** Not a hand-kept list: a row
follows iff its `SCHOOL_PATH` begins with the FK that points at the person.
`Achievement.SCHOOL_PATH = 'student__user__school'` starts with `student`, the
same FK that links it to the student — so it travels. `Enrollment` is linked by
`student` but anchored on `class_group__school`, so it belongs to school A's
timetable and stays. That rule needs no maintenance when a model is added.
"""

from core.checks import ACTOR_FIELDS
from apps.home.models import AcademicYear


def _profiles(user):
    """The person-level rows that move with a user, plus the user itself."""
    anchors = [user]
    for attr in ('student', 'teacher', 'parent', 'supervisor', 'clubmanager'):
        profile = getattr(user, attr, None)
        if profile is not None:
            anchors.append(profile)
    return anchors


def _follows(model, fk_name):
    """Does a row of `model`, linked by `fk_name`, move with the person?"""
    path = getattr(model, 'SCHOOL_PATH', None)
    return bool(path) and path.split('__')[0] == fk_name


def stranded_by_move(user):
    """{label: count} of rows that would be left in the user's current school.

    Empty means the move is clean. Anything in it is a reason to refuse, and
    the label is what the admin shows the person who tried.
    """
    blockers = {}
    for anchor in _profiles(user):
        # Reverse FKs: enrollments, grades, notifications, reports…
        for relation in anchor._meta.related_objects:
            model = relation.related_model
            field_name = relation.field.name
            if model._meta.proxy or not getattr(model, 'SCHOOL_PATH', None):
                continue
            if field_name in ACTOR_FIELDS:
                # `uploaded_by`, `deleted_by`: the row records that this person
                # acted, it is not theirs to take. Moving its actor strands
                # nothing — the row belonged to that school all along.
                continue
            if _follows(model, field_name):
                continue
            count = model._base_manager.filter(**{field_name: anchor}).count()
            if count:
                label = str(model._meta.verbose_name_plural)
                blockers[label] = blockers.get(label, 0) + count

        # Forward M2M: a teacher's subjects, a parent's children. `.add()` is
        # guarded against creating these across schools, but rows that were
        # legal when written become cross-tenant the moment their owner moves.
        for field in anchor._meta.many_to_many:
            target = field.related_model
            if not getattr(target, 'SCHOOL_PATH', None):
                continue
            # Queried from the target side through `_base_manager`, not through
            # `anchor.<field>`: the related manager is the scoped one, so it
            # would answer "none" for anything outside the active school —
            # which is precisely the set this function exists to count.
            count = (
                target._base_manager
                .filter(**{field.related_query_name(): anchor})
                .exclude(**{target.SCHOOL_PATH: user.school_id})
                .count()
            )
            if count:
                label = str(target._meta.verbose_name_plural)
                blockers[label] = blockers.get(label, 0) + count
    return blockers


def realign_profile(user):
    """Re-point the profile fields that would otherwise block every save.

    Only reached for a user the check above cleared, so there is no academic
    record to reconcile — just two nullable fields on `Student` that still name
    the old school and would raise `CrossSchoolWriteError` on the next save.

    Returns human-readable strings describing what changed. The caller must
    show them: a silent field change during what looked like a one-field edit
    is how someone loses an Orda house without noticing.
    """
    student = getattr(user, 'student', None)
    if student is None or user.school_id is None:
        return []

    changes, updated = [], []

    if student.school_group_id is not None:
        old = student.school_group
        if old.school_id != user.school_id:
            # The same house by name in the new school, if it has one. Matched
            # on the name rather than carried across by id, for the reason
            # `repair_tenant_rows` does the same: the id belongs to the other
            # tenant.
            twin = type(old)._base_manager.filter(
                school_id=user.school_id, name=old.name).first()
            student.school_group = twin
            updated.append('school_group')
            changes.append(
                f'Orda house "{old.name}" → '
                + ('the house of that name in the new school' if twin
                   else 'cleared — the new school has no house of that name')
            )

    if student.academic_year_id is not None:
        old_year = student.academic_year
        if old_year.school_id != user.school_id:
            # The new school's *active* year, not the same year string: year
            # rows are per-school since §1b, and "active" is what every other
            # code path means by the current one.
            replacement = AcademicYear._base_manager.filter(
                school_id=user.school_id, is_active=True).first()
            student.academic_year = replacement
            updated.append('academic_year')
            changes.append(
                f'academic year "{old_year.year}" → '
                + _year_change_wording(old_year, replacement)
            )

    if updated:
        student.save(update_fields=updated)
    return changes


def _year_change_wording(old_year, replacement):
    """Say what changed, when the two rows are usually named the same thing.

    Years are per-school since §1b, and both schools follow the same national
    calendar — so the overwhelmingly common case is re-pointing "2026/2027" at
    a *different row also called* "2026/2027". Printing both names produced
    `2026/2027 → 2026/2027`, which reads as a bug rather than as the tenancy
    fix it is. Name the row, not just the string.
    """
    if replacement is None:
        return 'cleared — the new school has no active year'
    if replacement.year == old_year.year:
        return (
            f'the new school\'s own "{replacement.year}" (a different row, '
            f'#{replacement.pk} — each school keeps its own year, so a student '
            f'must point at their own school\'s copy)'
        )
    return f'"{replacement.year}", the new school\'s active year'
