"""Phase 7: standing a tenant up, and cleaning up after phase 1.

`create_school` replaces a five-step manual sequence whose fourth step had been
crashing since phase 1. `repair_tenant_rows` is the read-side twin of the
phase 6 write rules — it re-runs them over rows that already exist.

The residue these tests plant is planted with `QuerySet.update()`, deliberately:
that is the write path phase 6 measured as invisible to `save()`, so it is the
only way to produce from Python the rows this command exists to find. Note what
that implies about coverage — `SubjectOffering.subject` cannot be corrupted here
at all, because `home/0040`'s composite FK refuses it at the database. Its
residue exists only on a database that has not run 0040 yet, which is precisely
when this command is meant to be used.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.authentication.models import CustomUser, School, SchoolGroup, Student
from apps.home.models import AcademicYear
from core import factories as f
from core.tenancy import all_schools, school_scope

pytestmark = [pytest.mark.django_db, pytest.mark.no_auto_scope]


@pytest.fixture(autouse=True)
def _enforce(settings):
    settings.SCHOOL_SCOPE_MODE = 'enforce'


def _run(*args):
    """Call the repair command, returning (exit_code, stdout)."""
    from io import StringIO
    out = StringIO()
    try:
        call_command('repair_tenant_rows', *args, stdout=out)
    except SystemExit as exc:
        return exc.code, out.getvalue()
    return 0, out.getvalue()


# ── create_school ───────────────────────────────────────────────────────────

def test_it_creates_the_whole_tenant():
    call_command(
        'create_school', '--slug', 'astana_29', '--name', 'Astana 29',
        '--admin-email', 'head@astana29.kz', '--year', '2026/2027',
        verbosity=0,
    )

    school = School.objects.get(slug='astana_29')
    with school_scope(school):
        assert AcademicYear.objects.filter(is_active=True).count() == 1
        assert SchoolGroup.objects.count() == 4
    admin = CustomUser.objects.get(username='head@astana29.kz')
    assert admin.school_id == school.pk
    assert admin.groups.filter(name=CustomUser.GROUP_ADMIN).exists()
    # App-level Admin, not Django staff: /admin/ is superuser territory, and
    # is_staff here would grant a login that shows an empty switcher.
    assert not admin.is_staff


def test_a_second_run_creates_nothing_new():
    args = ('create_school', '--slug', 'astana_29', '--name', 'Astana 29',
            '--admin-email', 'head@astana29.kz', '--year', '2026/2027')
    call_command(*args, verbosity=0)
    call_command(*args, verbosity=0)

    school = School.objects.get(slug='astana_29')
    with school_scope(school):
        assert AcademicYear.objects.count() == 1
        assert SchoolGroup.objects.count() == 4
    assert CustomUser.objects.filter(username='head@astana29.kz').count() == 1


def test_dry_run_writes_nothing():
    call_command(
        'create_school', '--slug', 'astana_29', '--name', 'Astana 29',
        '--admin-email', 'head@astana29.kz', '--year', '2026/2027',
        '--dry-run', verbosity=0,
    )

    assert not School.objects.filter(slug='astana_29').exists()
    assert not CustomUser.objects.filter(username='head@astana29.kz').exists()


def test_a_username_taken_by_another_school_is_refused():
    """Usernames are global — finding out at the INSERT is a poor way to learn it."""
    from django.core.management.base import CommandError

    other = f.SchoolFactory(slug='other')
    with school_scope(other):
        f.AdminUserFactory(school=other, username='head@astana29.kz')

    with pytest.raises(CommandError, match='already exists'):
        call_command(
            'create_school', '--slug', 'astana_29', '--name', 'Astana 29',
            '--admin-email', 'head@astana29.kz', verbosity=0,
        )
    assert not School.objects.filter(slug='astana_29').exists()


def test_the_year_is_the_schools_own():
    """Per-school since §1b, so a new tenant needs one or it cannot enrol."""
    existing = f.SchoolFactory(slug='existing')
    with school_scope(existing):
        f.AcademicYearFactory(school=existing, year='2026/2027', is_active=True)

    call_command(
        'create_school', '--slug', 'astana_29', '--name', 'Astana 29',
        '--year', '2026/2027', verbosity=0,
    )

    new = School.objects.get(slug='astana_29')
    with all_schools():
        years = AcademicYear.objects.filter(year='2026/2027')
        assert years.count() == 2
        assert {y.school_id for y in years} == {existing.pk, new.pk}


# ── repair_tenant_rows ──────────────────────────────────────────────────────

@pytest.fixture
def misfiled_student():
    """A student in school B wearing school A's Orda house.

    Planted with `.update()`, which never calls save() — the exact hole
    phase 6's layer 3 exists for, and one no composite FK covers.
    """
    a, b = f.SchoolFactory(slug='a'), f.SchoolFactory(slug='b')
    with school_scope(a):
        house_a = SchoolGroup.objects.create(school=a, name='Aq Orda')
    with school_scope(b):
        student = f.StudentFactory(user=f.StudentUserFactory(school=b))
        Student.objects.filter(pk=student.pk).update(school_group=house_a)
    return a, b, student, house_a


def test_a_clean_database_reports_nothing():
    f.SchoolFactory(slug='a')
    code, out = _run()
    assert code == 0
    assert 'No cross-tenant rows' in out


def test_it_finds_the_misfiled_row_and_refuses_to_exit_clean(misfiled_student):
    a, b, student, house_a = misfiled_student

    code, out = _run()

    assert code == 1
    assert 'authentication.Student' in out
    assert f'#{student.pk}' in out and 'school_group' in out


def test_report_only_changes_nothing(misfiled_student):
    a, b, student, house_a = misfiled_student

    _run()

    student.refresh_from_db()
    assert student.school_group_id == house_a.pk


def test_apply_repoints_at_the_twin_in_the_right_school(misfiled_student):
    """The twin is matched on its natural key, never on id."""
    a, b, student, house_a = misfiled_student
    with school_scope(b):
        house_b = SchoolGroup.objects.create(school=b, name='Aq Orda')

    code, out = _run('--apply')

    student.refresh_from_db()
    assert student.school_group_id == house_b.pk
    assert code == 0


def test_apply_leaves_it_alone_when_there_is_no_twin(misfiled_student):
    """Creating the other school's house is a judgement, not a repair."""
    a, b, student, house_a = misfiled_student

    code, out = _run('--apply')

    student.refresh_from_db()
    assert student.school_group_id == house_a.pk
    assert code == 1
    assert 'LEFT ALONE' in out


def test_clone_missing_creates_the_twin(misfiled_student):
    a, b, student, house_a = misfiled_student

    code, out = _run('--apply', '--clone-missing')

    student.refresh_from_db()
    assert code == 0
    assert student.school_group_id != house_a.pk
    with all_schools():
        twin = SchoolGroup.objects.get(pk=student.school_group_id)
    assert twin.school_id == b.pk and twin.name == 'Aq Orda'


def test_a_wrong_denormalised_column_is_restamped():
    """The other repair: a school column that disagrees with its source.

    `Club.school` is derived from `manager__user`. Move the manager and the
    column goes stale — the mixin only runs on save, and nothing re-derives.
    """
    from apps.achievement.models import Club

    a, b = f.SchoolFactory(slug='a'), f.SchoolFactory(slug='b')
    with school_scope(a):
        club = f.ClubFactory(school=a)
    # Only the column moves: the manager and the year stay in school A. That is
    # the phase-1 residue shape — the parents were always right and the column
    # was the thing being guessed at.
    with all_schools():
        Club.all_objects.filter(pk=club.pk).update(school=b)

    code, out = _run('--apply', '--model', 'achievement.Club')

    with all_schools():
        club.refresh_from_db()
    assert club.school_id == a.pk
    assert code == 0


def test_the_admin_group_is_reused_not_duplicated():
    call_command(
        'create_school', '--slug', 'astana_29', '--name', 'Astana 29',
        '--admin-email', 'head@astana29.kz', verbosity=0,
    )
    assert Group.objects.filter(name=CustomUser.GROUP_ADMIN).count() == 1
