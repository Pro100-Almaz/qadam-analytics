"""Factories build their whole graph inside the active school.

This is what makes a two-school `build_world()` possible. Without it, the only
way to put a nested object in school B is to spell out every branch
(`offering__subject__school=b`, ...) — and a branch you forget does not fail,
it silently builds an offering in B whose subject is in A. That is the exact
shape of the real production defect (offerings 347/348), so a world built that
way would let the isolation tests pass while measuring nothing.
"""

import pytest
from django.test import override_settings

from apps.authentication.models import School
from apps.lesson.models import Lesson
from core.factories import (
    DEFAULT_TEST_SCHOOL_SLUG,
    _current_school,
    ClassGroupFactory,
    LessonFactory,
    SchoolFactory,
    SubjectFactory,
    SubjectOfferingFactory,
    UserFactory,
)
from core.tenancy import all_schools, school_scope


@pytest.fixture
def school_b():
    return SchoolFactory(slug='school_b', name='School B')


@pytest.mark.django_db
def test_the_ambient_scope_is_the_default(school_b):
    with school_scope(school_b):
        assert SubjectFactory().school == school_b
        assert ClassGroupFactory().school == school_b
        assert UserFactory().school == school_b


@pytest.mark.django_db
@override_settings(SCHOOL_SCOPE_MODE='enforce')
def test_a_nested_graph_lands_in_one_school(school_b):
    """The case `school=` alone cannot reach: three levels down.

    Pins the mode because the second half asserts what is *not* visible, and
    under 'off' the filter is switched off entirely — the row would be visible
    from both schools and the test would fail for a reason that says nothing
    about factories. The same idiom as ENFORCE in test_tenancy.py.
    """
    with school_scope(school_b):
        lesson = LessonFactory()

    offering = lesson.offering
    assert offering.school == school_b
    assert offering.subject.school == school_b          # 2 levels down
    assert offering.class_group.school == school_b      # 2 levels down

    # Lesson carries no school column of its own — it scopes through
    # `offering__school`, so the property to assert is visibility, not a field.
    with school_scope(school_b):
        assert Lesson.objects.filter(pk=lesson.pk).exists()
    with school_scope(SchoolFactory(slug='school_a', name='School A')):
        assert not Lesson.objects.filter(pk=lesson.pk).exists()


@pytest.mark.django_db
def test_two_worlds_do_not_bleed_into_each_other(school_b):
    school_a = SchoolFactory(slug='school_a', name='School A')

    with school_scope(school_a):
        a = SubjectOfferingFactory()
    with school_scope(school_b):
        b = SubjectOfferingFactory()

    assert {a.school, a.subject.school, a.class_group.school} == {school_a}
    assert {b.school, b.subject.school, b.class_group.school} == {school_b}


@pytest.mark.django_db
def test_an_explicit_argument_still_wins(school_b):
    """Deliberate mismatches stay expressible — the negative tests need them."""
    school_a = SchoolFactory(slug='school_a', name='School A')
    with school_scope(school_b):
        subject = SubjectFactory(school=school_a)
    assert subject.school == school_a


@pytest.mark.django_db
@pytest.mark.no_auto_scope
def test_with_no_scope_the_fallback_resolves_the_default_school():
    """The fallback picks a school; it does not make unscoped writes possible.

    Building the model itself still fails closed with no scope under 'enforce'
    — see `test_writes_fail_closed_too` — so this asserts the resolution only.
    `School.objects` is unscoped by design (you cannot scope the tenant root),
    which is what lets the fallback run at all.
    """
    assert _current_school().slug == DEFAULT_TEST_SCHOOL_SLUG


@pytest.mark.django_db
def test_under_all_schools_it_falls_back_too():
    with all_schools():
        subject = SubjectFactory()
    assert subject.school.slug == DEFAULT_TEST_SCHOOL_SLUG


@pytest.mark.django_db
def test_students_get_one_shared_active_year_not_one_each():
    from core.factories import StudentFactory

    first = StudentFactory()
    second = StudentFactory()
    assert first.academic_year is not None
    assert first.academic_year == second.academic_year
    with all_schools():
        assert School.objects.filter(slug='test_school').count() == 1
