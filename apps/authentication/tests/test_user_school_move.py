"""Moving a user between schools in the admin: allowed only when it is clean.

The capability exists for one job — correcting a user filed in the wrong
school, which is what `legacy_school` is kept as the record of. It is not a
mid-year transfer: a student's enrollments and marks are anchored to the old
school's class groups and offerings, so moving the person alone splits their
record across two tenants and leaves the profile failing its own consistency
check. These pin both halves: the clean move works, the dirty one is refused
with a message that names what is in the way.
"""

import pytest

from apps.authentication.admin import CustomUserChangeForm
from apps.authentication.models import Student
from apps.authentication.school_transfer import (
    realign_profile, stranded_by_move,
)
from core import factories as f
from core.tenancy import school_scope

pytestmark = [pytest.mark.django_db, pytest.mark.no_auto_scope]


@pytest.fixture(autouse=True)
def _enforce(settings):
    settings.SCHOOL_SCOPE_MODE = 'enforce'


@pytest.fixture
def two_schools():
    return f.SchoolFactory(slug='a'), f.SchoolFactory(slug='b')


def _move_form(user, school):
    """The admin change form, filled the way the browser would fill it.

    Built from the instance rather than by hand: `UserChangeForm` is
    `fields = '__all__'`, so a hand-written dict fails on whichever required
    field the test author forgot rather than on the thing under test.
    """
    from django.forms.models import model_to_dict

    data = {
        key: value for key, value in model_to_dict(user).items()
        if value is not None
    }
    data['school'] = school.pk
    data['date_joined'] = user.date_joined.strftime('%Y-%m-%d %H:%M:%S')
    return CustomUserChangeForm(data=data, instance=user)


# ── the check itself ────────────────────────────────────────────────────────

def test_a_fresh_user_has_nothing_to_strand(two_schools):
    a, _ = two_schools
    with school_scope(a):
        user = f.TeacherUserFactory(school=a)

    assert stranded_by_move(user) == {}


def test_an_enrolled_student_does(two_schools):
    a, _ = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
        f.EnrollmentFactory(student=student, class_group=f.ClassGroupFactory(school=a))

    assert stranded_by_move(student.user)


def test_achievements_are_not_blockers_because_they_travel(two_schools):
    """A row follows its person iff its SCHOOL_PATH starts at that person.

    `Achievement.SCHOOL_PATH = 'student__user__school'` — linked by `student`
    and anchored through `student`, so it moves. Counting it as a blocker would
    refuse moves that are perfectly clean.
    """
    from apps.achievement.models import Achievement

    a, _ = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
        Achievement.objects.create(
            student=student, academic_year=f._active_academic_year(a),
            description='Olympiad',
        )

    assert stranded_by_move(student.user) == {}


def test_being_the_actor_on_someone_elses_row_is_not_a_blocker(two_schools):
    """`deleted_by` and friends record that a person acted, not that it is theirs."""
    a, _ = two_schools
    with school_scope(a):
        admin_user = f.AdminUserFactory(school=a)
        club = f.ClubFactory(school=a)
        club.soft_delete(user=admin_user)

    assert stranded_by_move(admin_user) == {}


# ── the picker the admin actually renders ───────────────────────────────────

def _admin_form_for(user, acting_as):
    """The form the change page builds, through the real admin machinery.

    Calling `CustomUserChangeForm` directly is not a substitute: the school
    queryset is chosen by `formfield_for_foreignkey` during `get_form`, so a
    test that skips `get_form` cannot see what the page will show. That gap is
    how the picker shipped still pinned to one school.
    """
    from django.contrib import admin as django_admin
    from django.test import RequestFactory

    request = RequestFactory().get('/admin/')
    request.user = acting_as
    model_admin = django_admin.site._registry[type(user)]
    return model_admin.get_form(request, user)


def test_the_change_page_offers_every_school(two_schools):
    a, b = two_schools
    with school_scope(a):
        user = f.TeacherUserFactory(school=a)
        superuser = f.UserFactory(school=a, is_superuser=True, is_staff=True)

        schools = _admin_form_for(user, superuser).base_fields['school'].queryset

    # A superset, not an equality: `authentication/0037` seeds the two original
    # schools, so the test database holds more than this fixture made. What
    # matters is that a school the user is *not* in is offered at all.
    offered = set(schools.values_list('pk', flat=True))
    assert {a.pk, b.pk} <= offered
    assert offered != {a.pk}


def test_the_add_page_stays_pinned_to_the_active_school(two_schools):
    """The original lock, and it is still right: a new row goes where you are."""
    from django.contrib import admin as django_admin
    from django.test import RequestFactory

    a, b = two_schools
    with school_scope(a):
        superuser = f.UserFactory(school=a, is_superuser=True, is_staff=True)
        request = RequestFactory().get('/admin/')
        request.user = superuser
        model_admin = django_admin.site._registry[type(superuser)]

        schools = model_admin.get_form(
            request, None).base_fields['school'].queryset

    assert set(schools.values_list('pk', flat=True)) == {a.pk}


# ── the form gate ───────────────────────────────────────────────────────────

def test_the_form_allows_a_clean_move(two_schools):
    a, b = two_schools
    with school_scope(a):
        user = f.TeacherUserFactory(school=a)

    form = _move_form(user, b)

    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.school_id == b.pk


def test_the_form_refuses_and_names_the_blockers(two_schools):
    a, b = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
        f.EnrollmentFactory(student=student, class_group=f.ClassGroupFactory(school=a))

    form = _move_form(student.user, b)

    assert not form.is_valid()
    assert 'school' in form.errors
    assert 'would stay behind' in form.errors['school'][0]
    student.user.refresh_from_db()
    assert student.user.school_id == a.pk


def test_editing_a_user_without_touching_school_is_unaffected(two_schools):
    """The gate must only fire on an actual change of school."""
    a, _ = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
        f.EnrollmentFactory(student=student, class_group=f.ClassGroupFactory(school=a))

    form = _move_form(student.user, a)

    assert form.is_valid(), form.errors


# ── what happens to the profile afterwards ──────────────────────────────────

def test_the_profile_is_realigned_so_it_stays_saveable(two_schools):
    """Otherwise every later save raises CrossSchoolWriteError."""
    a, b = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
    with school_scope(b):
        b_house = f.SchoolGroupFactory(school=b, name=student.school_group.name)

    student.user.school = b
    student.user.save()
    changes = realign_profile(student.user)

    student.refresh_from_db()
    assert student.school_group_id == b_house.pk
    assert changes  # it must say what it did, not do it silently
    with school_scope(b):
        Student._base_manager.get(pk=student.pk).save()  # no longer raises


def test_realignment_clears_rather_than_guesses(two_schools):
    """No house of that name in the new school: cleared, and said so."""
    a, b = two_schools
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))

    student.user.school = b
    student.user.save()
    changes = realign_profile(student.user)

    student.refresh_from_db()
    assert student.school_group_id is None
    assert any('cleared' in line for line in changes)
