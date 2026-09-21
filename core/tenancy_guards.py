"""§7 layer 2: the cross-tenant guard for many-to-many relations.

`SchoolConsistentModel` covers rows that are *saved*. `.add()` saves nothing —
it INSERTs straight into the through table — so a scoped manager and a
save-time validator both miss it entirely, and the write that stitches school
A's parent to school B's student looks like ordinary ORM use:

    parent.students.add(student_from_the_other_school)

Five relations can do it today: `Parent.students`, `Teacher.subjects`,
`Student.subjects`, `Club.members` and `ClassGroupCollection.minor_groups`.
The receiver is connected with **no sender** rather than five times, so a sixth
relation added later is guarded the day it is written — the failure mode of the
explicit list is a silent hole, and the cost of the blanket version is one
early `return` on every unrelated m2m (`user.groups`, permissions), where one
side has no SCHOOL_PATH.
"""

from django.db.models.signals import m2m_changed

from core.models import school_id_of
from core.tenancy import CrossSchoolWriteError


def _schools_of(model, pk_set):
    """The distinct schools of `pk_set`, in one query.

    `_base_manager`, unscoped on purpose: the question is which tenant these
    rows belong to, and a scoped queryset would answer it by hiding the rows
    that make the answer interesting.
    """
    path = getattr(model, 'SCHOOL_PATH', None)
    if not path:
        return set()
    found = model._base_manager.filter(pk__in=pk_set).values_list(path, flat=True)
    return {school_id for school_id in found if school_id is not None}


def guard_cross_school_m2m(sender, instance, action, reverse, model, pk_set, **kwargs):
    """Refuse an `.add()` that would link rows from two schools.

    Only `pre_add` — removing a link cannot create a cross-tenant one, and
    `pre_clear` carries no pks. `reverse` needs no branch: either way
    `instance` is one side and `pk_set` names rows of `model` on the other, so
    the comparison is the same.
    """
    if action != 'pre_add' or not pk_set:
        return
    if not getattr(type(instance), 'SCHOOL_PATH', None):
        return
    instance_school = school_id_of(instance)
    if instance_school is None:
        return
    foreign = _schools_of(model, pk_set) - {instance_school}
    if not foreign:
        return
    raise CrossSchoolWriteError(
        f'{type(instance).__name__} #{instance.pk} belongs to school '
        f'#{instance_school}, so it cannot be linked to '
        f'{model.__name__} rows from school(s) '
        f'{", ".join(f"#{s}" for s in sorted(foreign))}. Nothing was linked.'
    )


def register_m2m_guard():
    """Connect once, from AppConfig.ready(), so every process has it."""
    m2m_changed.connect(
        guard_cross_school_m2m, dispatch_uid='tenancy_cross_school_m2m',
    )
