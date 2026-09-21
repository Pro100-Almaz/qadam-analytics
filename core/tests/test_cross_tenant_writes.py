"""§7: the three layers that stop a single row belonging to two schools.

The scoped manager is about *reading*. It narrows what a query can find, which
means a cross-school id cannot normally be looked up — but "normally" is doing
a lot of work there: `_base_manager`, an admin form, a management script, a
serializer that resolved an object before the scope was entered, and a raw
`UPDATE` all reach rows the manager would have hidden. These tests cover what
happens when such an id arrives anyway:

1. `SchoolConsistentModel.save()` — the ORM save path.
2. `guard_cross_school_m2m` — `.add()`, which never calls save().
3. the composite foreign keys in `home/0040` — Postgres, which does not care
   which language the write came from.

Every test pins `SCHOOL_SCOPE_MODE='enforce'`: these assert on writes rather
than reads, but a test that builds its world in two schools has to do so with
the filter live, or it is not reproducing the situation it claims to.
"""

import pytest
from django.db import IntegrityError, connection, transaction

from apps.achievement.models import Club
from apps.authentication.models import (
    Parent, PsychologicalState, PsychologicalStateTemplates, Student,
)
from apps.home.models import Enrollment, SubjectOffering
from apps.lesson.models import SubjectSchedule
from core import factories as f
from core.checks import check_join_models_validate_school_consistency
from core.models import SchoolConsistentModel
from core.tenancy import CrossSchoolWriteError, all_schools, school_scope

pytestmark = [pytest.mark.django_db, pytest.mark.no_auto_scope]


@pytest.fixture(autouse=True)
def _enforce(settings):
    settings.SCHOOL_SCOPE_MODE = 'enforce'


@pytest.fixture
def two_schools():
    return f.SchoolFactory(slug='school_a'), f.SchoolFactory(slug='school_b')


# ── layer 1: the save path ──────────────────────────────────────────────────

def test_an_offering_cannot_marry_two_schools(two_schools):
    """The canonical cross-tenant row: A's subject offered to B's class."""
    a, b = two_schools
    with school_scope(a):
        subject = f.SubjectFactory(school=a)
    with school_scope(b):
        class_group = f.ClassGroupFactory(school=b)

    with school_scope(a), pytest.raises(CrossSchoolWriteError) as exc:
        SubjectOffering.objects.create(
            subject=subject, class_group=class_group, max_points=100,
        )

    assert 'subject' in str(exc.value) and 'class_group' in str(exc.value)
    with all_schools():
        assert SubjectOffering.objects.count() == 0


def test_a_consistent_offering_gets_its_school_stamped(two_schools):
    """Derive when you can: nobody passes `school=` and it is still right."""
    a, _ = two_schools
    with school_scope(a):
        offering = SubjectOffering.objects.create(
            subject=f.SubjectFactory(school=a),
            class_group=f.ClassGroupFactory(school=a),
            max_points=100,
        )

    assert offering.school_id == a.pk


def test_a_model_with_no_school_column_is_guarded_too(two_schools):
    """Enrollment reaches its school by path and still cannot cross one."""
    a, b = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
    with school_scope(b):
        class_group = f.ClassGroupFactory(school=b)

    with school_scope(a), pytest.raises(CrossSchoolWriteError):
        Enrollment.objects.create(student=student, class_group=class_group)

    with all_schools():
        assert Enrollment.objects.count() == 0


def test_an_explicit_school_that_contradicts_the_parents_is_refused(two_schools):
    """The column is not a second opinion — it has to agree with the row."""
    a, b = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))

    with school_scope(a), pytest.raises(CrossSchoolWriteError) as exc:
        PsychologicalState.objects.create(
            student=student, school=b, comment='mis-filed',
        )

    assert 'contradicts' in str(exc.value)
    with all_schools():
        assert PsychologicalState.objects.count() == 0


def test_a_half_populated_row_is_valid(two_schools):
    """Skip-None, not fail-on-None: a school-wide schedule has neither FK.

    This is the case the nullable-path rule exists for. If validation treated
    an unset FK as an error, every school-wide SubjectSchedule would become
    unsaveable — the write-side twin of the INNER JOIN bug in §1.
    """
    a, _ = two_schools
    with school_scope(a):
        schedule = SubjectSchedule.objects.create(
            school=a, quarter=1, description='Assembly, whole school',
        )

    assert schedule.pk and schedule.school_id == a.pk


def test_two_half_populated_fks_that_disagree_are_not(two_schools):
    a, b = two_schools
    with school_scope(a):
        offering = f.SubjectOfferingFactory(school=a)
    with school_scope(b):
        class_group = f.ClassGroupFactory(school=b)

    with school_scope(a), pytest.raises(CrossSchoolWriteError):
        SubjectSchedule.objects.create(
            offering=offering, class_group=class_group, quarter=1,
        )


def test_the_actor_may_belong_to_another_school(two_schools):
    """A superuser administering school A from the §9a switcher is normal.

    `deleted_by` and friends record who acted, not what the row is about, so
    they are excluded from SCHOOL_CONSISTENT_FIELDS on purpose. Requiring them
    to match would break exactly the cross-school administration the header
    switcher exists to provide.
    """
    a, b = two_schools
    with school_scope(b):
        admin_from_b = f.AdminUserFactory(school=b)
    with school_scope(a):
        club = f.ClubFactory(school=a)

        club.soft_delete(user=admin_from_b)

    club.refresh_from_db()
    assert club.is_deleted and club.deleted_by_id == admin_from_b.pk
    assert club.school_id == a.pk


def test_a_clubs_manager_and_year_must_be_its_own(two_schools):
    a, b = two_schools
    with school_scope(a):
        year_a = f.AcademicYearFactory(school=a, is_active=True)
    with school_scope(b):
        manager_b = f.ClubManagerFactory(user=f.ClubManagerUserFactory(school=b))

    with school_scope(a), pytest.raises(CrossSchoolWriteError):
        Club.objects.create(
            manager=manager_b, academic_year=year_a, name='Chess',
            start_date='2026-09-01', end_date='2027-05-01',
        )


# ── the check that keeps the declarations honest ────────────────────────────

def test_every_join_model_declares_which_fks_must_agree():
    """`manage.py check` is the ratchet, so assert it is actually clean."""
    assert check_join_models_validate_school_consistency() == []


def test_a_join_model_without_the_declaration_fails_the_check(monkeypatch):
    """And assert the ratchet has teeth, rather than trusting the empty list."""
    monkeypatch.setattr(Enrollment, 'SCHOOL_CONSISTENT_FIELDS', ())

    errors = check_join_models_validate_school_consistency()

    assert [e.id for e in errors] == ['tenancy.E008']
    assert 'home.Enrollment' in errors[0].msg


def test_declaring_models_inherit_the_base():
    """A tuple on a model that does not read it would be decoration."""
    for model in (Enrollment, SubjectOffering, Student, Club, SubjectSchedule):
        assert issubclass(model, SchoolConsistentModel), model


# ── layer 2: .add(), which never calls save() ───────────────────────────────

def test_a_parent_cannot_adopt_another_schools_student(two_schools):
    a, b = two_schools
    with school_scope(a):
        parent = Parent.objects.create(user=f.ParentUserFactory(school=a))
    with school_scope(b):
        student_b = f.StudentFactory(user=f.StudentUserFactory(school=b))

    # The savepoint is load-bearing, not tidiness: Django wraps `.add()` in
    # `atomic(savepoint=False)`, so raising from `pre_add` marks the enclosing
    # transaction for rollback. A caller that means to carry on afterwards —
    # this assertion, or a view catching the error — needs its own savepoint.
    with school_scope(a), pytest.raises(CrossSchoolWriteError):
        with transaction.atomic():
            parent.students.add(student_b)

    with all_schools():
        assert parent.students.count() == 0


def test_the_same_add_is_fine_inside_one_school(two_schools):
    a, _ = two_schools
    with school_scope(a):
        parent = Parent.objects.create(user=f.ParentUserFactory(school=a))
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))

        parent.students.add(student)

        assert parent.students.count() == 1


def test_the_reverse_direction_is_guarded_too(two_schools):
    """`.add()` from the other end of the same relation is the same write."""
    a, b = two_schools
    with school_scope(a):
        parent_a = Parent.objects.create(user=f.ParentUserFactory(school=a))
    with school_scope(b):
        student_b = f.StudentFactory(user=f.StudentUserFactory(school=b))

    with school_scope(b), pytest.raises(CrossSchoolWriteError):
        with transaction.atomic():
            student_b.parent.add(parent_a)


def test_subjects_from_another_school_cannot_be_assigned(two_schools):
    """Student.subjects — a different relation, covered by the same receiver."""
    a, b = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
    with school_scope(b):
        subject_b = f.SubjectFactory(school=b)

    with school_scope(a), pytest.raises(CrossSchoolWriteError):
        with transaction.atomic():
            student.subjects.add(subject_b)


def _tenant_m2m_relations():
    """(owner, field) for every m2m between two tenant models."""
    from core.checks import _tenant_models
    for model in _tenant_models():
        for field in model._meta.many_to_many:
            if getattr(field.related_model, 'SCHOOL_PATH', None):
                yield model, field


def test_the_guard_covers_every_tenant_to_tenant_m2m():
    """The receiver has no sender, so coverage is a property of the models.

    It engages only when *both* ends declare a SCHOOL_PATH. Five relations
    qualify today; this fails the day a sixth is added to a model that does
    not, which is the shape the guard would silently skip.
    """
    relations = list(_tenant_m2m_relations())

    assert len(relations) == 5, [f'{m._meta.label}.{f.name}' for m, f in relations]
    for model, field in relations:
        assert getattr(model, 'SCHOOL_PATH', None), f'{model._meta.label}.{field.name}'


def test_the_guard_is_connected():
    """Connected from AppConfig.ready(), so nothing imports it by accident."""
    from django.db.models.signals import m2m_changed

    from core.tenancy_guards import guard_cross_school_m2m

    receivers = [r[1]() for r in m2m_changed.receivers]
    assert guard_cross_school_m2m in receivers


# ── layer 3: Postgres, for writes that never touch Python ───────────────────

def _immediate():
    """Deferred FKs fire at COMMIT, which a test transaction never reaches."""
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def test_a_raw_update_cannot_repoint_an_offering_across_schools(two_schools):
    """The layer that survives a script, a shell, or a hand-written UPDATE."""
    a, b = two_schools
    with school_scope(a):
        offering = f.SubjectOfferingFactory(school=a)
    with school_scope(b):
        subject_b = f.SubjectFactory(school=b)

    with pytest.raises(IntegrityError) as exc:
        with transaction.atomic():
            _immediate()
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE home_subjectoffering SET subject_id = %s WHERE id = %s',
                    [subject_b.pk, offering.pk],
                )

    assert 'offering_subject_same_school' in str(exc.value)


def test_a_raw_update_cannot_repoint_a_class_group_at_another_schools_year(two_schools):
    a, b = two_schools
    with school_scope(a):
        class_group = f.ClassGroupFactory(school=a)
    with school_scope(b):
        year_b = f.AcademicYearFactory(school=b, is_active=True)

    with pytest.raises(IntegrityError) as exc:
        with transaction.atomic():
            _immediate()
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE home_classgroup SET academic_year_id = %s WHERE id = %s',
                    [year_b.pk, class_group.pk],
                )

    assert 'classgroup_academic_year_same_school' in str(exc.value)


def test_a_class_group_with_no_year_stays_legal(two_schools):
    """MATCH SIMPLE: a composite FK with a NULL column is not checked.

    Worth pinning. If it were MATCH FULL instead, every subgroup with no
    academic year — which the model explicitly allows — would stop saving.
    """
    a, _ = two_schools
    with school_scope(a):
        class_group = f.ClassGroupFactory(school=a, academic_year=None)

    with transaction.atomic():
        _immediate()
        assert class_group.pk and class_group.academic_year_id is None


# ── the one required constraint ─────────────────────────────────────────────

def test_two_schools_may_use_the_same_template_name(two_schools):
    """The §7 relaxation: `name` was globally unique, so B was blocked by A."""
    a, b = two_schools

    with school_scope(a):
        PsychologicalStateTemplates.objects.create(name='Тревожность', school=a)
    with school_scope(b):
        PsychologicalStateTemplates.objects.create(name='Тревожность', school=b)

    with all_schools():
        assert PsychologicalStateTemplates.objects.filter(
            name='Тревожность').count() == 2


def test_one_school_still_may_not_repeat_a_template_name(two_schools):
    a, _ = two_schools
    with school_scope(a):
        PsychologicalStateTemplates.objects.create(name='Тревожность', school=a)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PsychologicalStateTemplates.objects.create(
                    name='Тревожность', school=a)
