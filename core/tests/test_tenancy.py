"""The scoping mechanism itself — core.tenancy.

Phase 10 adds the generic isolation suite across every model. These cover the
machinery those tests stand on: the contextvar, the three modes, and the
manager composition.
"""

import logging

import pytest
from django.test import override_settings

from apps.home.models import AcademicYear, Subject
from apps.lesson.models import Lesson
from core.factories import (
    AcademicYearFactory, LessonFactory, SchoolFactory, SubjectFactory,
)
from core.tenancy import (
    ALL, UNSET, SchoolScopeError, all_schools, apply_school_scope,
    get_active_school, no_school_scope, school_scope,
)

pytestmark = pytest.mark.django_db

ENFORCE = override_settings(SCHOOL_SCOPE_MODE='enforce')


@pytest.fixture
def two_schools():
    a = SchoolFactory(slug='school_a', name='School A')
    b = SchoolFactory(slug='school_b', name='School B')
    SubjectFactory(name='A-subject', school=a)
    SubjectFactory(name='B-subject', school=b)
    return a, b


# ── the contextvar ──

# These two assert what the ContextVar looks like with nothing entered, so
# they are precisely what `no_auto_scope` exists for: conftest's autouse
# `_default_scope` enters school A for every other test in the suite.

@pytest.mark.no_auto_scope
def test_scope_is_unset_by_default():
    assert get_active_school() is UNSET


@pytest.mark.no_auto_scope
def test_school_scope_sets_and_restores():
    school = SchoolFactory(slug='school_a')
    with school_scope(school):
        assert get_active_school() == school.pk
    assert get_active_school() is UNSET


def test_scopes_nest_and_unwind():
    a, b = SchoolFactory(slug='a'), SchoolFactory(slug='b')
    with school_scope(a):
        with school_scope(b):
            assert get_active_school() == b.pk
        assert get_active_school() == a.pk


def test_school_scope_accepts_a_pk():
    with school_scope(7):
        assert get_active_school() == 7


def test_school_scope_rejects_none():
    with pytest.raises(ValueError, match='all_schools'):
        with school_scope(None):
            pass


def test_all_schools_sets_the_sentinel():
    with all_schools():
        assert get_active_school() is ALL


# ── the three modes ──

@ENFORCE
def test_enforce_filters_to_the_active_school(two_schools):
    a, _ = two_schools
    with school_scope(a):
        assert [s.name for s in Subject.objects.all()] == ['A-subject']


@ENFORCE
def test_enforce_raises_with_no_scope(two_schools):
    with no_school_scope(), pytest.raises(SchoolScopeError, match='Subject'):
        list(Subject.objects.all())


@ENFORCE
def test_all_schools_sees_everything(two_schools):
    with all_schools():
        assert Subject.objects.count() == 2


@override_settings(SCHOOL_SCOPE_MODE='off')
def test_off_is_a_no_op(two_schools):
    with no_school_scope():
        assert Subject.objects.count() == 2


@override_settings(SCHOOL_SCOPE_MODE='warn')
def test_warn_logs_and_returns_unfiltered(two_schools, caplog):
    with no_school_scope(), caplog.at_level(logging.ERROR, logger='core.tenancy'):
        assert Subject.objects.count() == 2
    assert 'queried outside a school scope' in caplog.text


@override_settings(SCHOOL_SCOPE_MODE='warn')
def test_warn_still_filters_when_a_scope_is_active(two_schools):
    a, _ = two_schools
    with school_scope(a):
        assert Subject.objects.count() == 1


@override_settings(SCHOOL_SCOPE_MODE='nonsense')
def test_an_unknown_mode_is_rejected_rather_than_assumed(two_schools):
    with pytest.raises(ValueError, match='SCHOOL_SCOPE_MODE'):
        list(Subject.objects.all())


# ── shared models, and paths with joins ──

@ENFORCE
def test_a_model_with_no_school_path_is_untouched():
    from apps.home.models import GradeLevel
    with no_school_scope():
        assert GradeLevel.objects.count() >= 0  # no raise


def _lesson(school, title):
    return LessonFactory(
        title=title, offering__school=school,
        offering__class_group__school=school, offering__subject__school=school,
    )


@ENFORCE
def test_a_joined_path_scopes_too(two_schools):
    a, b = two_schools
    with all_schools():
        _lesson(a, 'A-lesson')
        _lesson(b, 'B-lesson')
    with school_scope(a):
        assert [x.title for x in Lesson.objects.all()] == ['A-lesson']


@ENFORCE
def test_writes_fail_closed_too(two_schools):
    """`Manager.create()` runs through get_queryset, so it is scoped as well."""
    with no_school_scope(), pytest.raises(SchoolScopeError):
        SubjectFactory(name='orphan')


# ── manager composition ──

@ENFORCE
def test_soft_delete_all_with_deleted_stays_scoped(two_schools):
    """The leak the plan flagged: these bypassed get_queryset entirely."""
    a, b = two_schools
    with all_schools():
        for school, title in ((a, 'A-lesson'), (b, 'B-lesson')):
            _lesson(school, title).soft_delete()

    with school_scope(a):
        assert Lesson.objects.count() == 0                      # soft-deleted
        assert [x.title for x in Lesson.all_objects.all()] == ['A-lesson']
        assert [x.title for x in Lesson.objects.all_with_deleted()] == ['A-lesson']
        assert [x.title for x in Lesson.objects.deleted_only()] == ['A-lesson']


@ENFORCE
def test_unscoped_manager_is_the_documented_escape_hatch(two_schools):
    a, b = two_schools
    with all_schools():
        _lesson(a, 'A-lesson')
        _lesson(b, 'B-lesson')
    with school_scope(a):
        assert Lesson.unscoped.count() == 2


@ENFORCE
def test_minor_class_group_manager_keeps_both_filters(two_schools):
    from apps.home.models import ClassGroup, MinorClassGroup
    a, b = two_schools
    with all_schools():
        year_a = AcademicYearFactory(school=a)
        MinorClassGroup.objects.create(academic_year=year_a, letter='Хор')
        ClassGroup.objects.create(academic_year=year_a, letter='7A', school=a)
        MinorClassGroup.objects.create(
            academic_year=AcademicYearFactory(school=b), letter='Шахматы')

    with school_scope(a):
        assert [g.letter for g in MinorClassGroup.objects.all()] == ['Хор']


@ENFORCE
def test_customuser_default_manager_stays_global(two_schools):
    """Login would break otherwise — ModelBackend uses _default_manager."""
    from apps.authentication.models import CustomUser
    from core.factories import UserFactory
    a, b = two_schools
    with all_schools():
        UserFactory(school=a, username='a@test.kz')
        UserFactory(school=b, username='b@test.kz')

    with no_school_scope():
        assert CustomUser.objects.get(username='b@test.kz')   # no raise
    with school_scope(a):
        assert CustomUser.objects.count() == 2
        assert CustomUser.in_school.count() == 1


# ── apply_school_scope directly ──

@ENFORCE
def test_apply_school_scope_is_idempotent_under_all(two_schools):
    with all_schools():
        qs = apply_school_scope(Subject.objects.all(), Subject)
        assert qs.count() == 2


@ENFORCE
def test_academic_year_singleton_resolves_per_school(two_schools):
    """The 20 `filter(is_active=True).first()` call sites become correct here."""
    a, b = two_schools
    with all_schools():
        AcademicYearFactory(school=a, year='2026/2027', is_active=True)
        AcademicYearFactory(school=b, year='2026/2027', is_active=True)

    with school_scope(a):
        assert AcademicYear.objects.filter(is_active=True).first().school_id == a.pk
    with school_scope(b):
        assert AcademicYear.objects.filter(is_active=True).first().school_id == b.pk
