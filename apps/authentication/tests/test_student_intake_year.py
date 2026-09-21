"""`Student.intake_year`: when this student entered, and nothing else.

It was a FK to `AcademicYear` called `academic_year`, which read as the
student's *current* year and was not one: it was stamped at creation and never
advanced, so after a rollover it named a past year while the student was
enrolled in the present one. These pin what it means now — a label that is
written once and then stays true, including across the two events that used to
corrupt or complicate it.
"""

import pytest

from apps.authentication.models import Student
from apps.authentication.school_transfer import realign_profile
from apps.home.models import AcademicYear
from core import factories as f
from core.tenancy import school_scope

pytestmark = [pytest.mark.django_db, pytest.mark.no_auto_scope]


@pytest.fixture(autouse=True)
def _enforce(settings):
    settings.SCHOOL_SCOPE_MODE = 'enforce'


def test_it_is_stamped_from_the_students_own_schools_active_year():
    a, b = f.SchoolFactory(slug='a'), f.SchoolFactory(slug='b')
    with school_scope(b):
        f.AcademicYearFactory(school=b, year='2000/2001', is_active=True)
    with school_scope(a):
        year_a = f.AcademicYearFactory(school=a, year='2026/2027', is_active=True)

        # Built while scoped to A, so A's year is the right answer — but the
        # signal reads it off `user.school`, not off the ambient scope, which
        # is what makes it behave the same in a script or a Celery worker.
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))

    assert student.intake_year == year_a.year


def test_it_is_a_label_not_a_pointer():
    """No FK, so no tenancy coupling and no row to keep in step."""
    assert not Student._meta.get_field('intake_year').is_relation


def test_it_is_not_overwritten_on_later_saves():
    a = f.SchoolFactory(slug='a')
    with school_scope(a):
        f.AcademicYearFactory(school=a, year='2024/2025', is_active=True)
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
        assert student.intake_year == '2024/2025'

        # A new year opens and is made active — a rollover, in miniature.
        AcademicYear._base_manager.filter(school=a).update(is_active=False)
        f.AcademicYearFactory(school=a, year='2025/2026', is_active=True)

        student.medical_features = 'updated for some other reason'
        student.save()

    student.refresh_from_db()
    assert student.intake_year == '2024/2025', (
        'the intake year moved with the active year — it records when the '
        'student entered, not which year is current'
    )


def test_it_survives_a_change_of_school_untouched():
    """The reason it stopped being a FK.

    Years are per-school since §1b, so as a FK this had to be re-pointed at the
    new school's row on every move or the profile failed its own consistency
    check. As a label there is nothing to re-point: the student entered in
    2024/2025 whichever school is holding them now.
    """
    a, b = f.SchoolFactory(slug='a'), f.SchoolFactory(slug='b')
    with school_scope(a):
        f.AcademicYearFactory(school=a, year='2024/2025', is_active=True)
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))
    with school_scope(b):
        f.AcademicYearFactory(school=b, year='2026/2027', is_active=True)

    student.user.school = b
    student.user.save()
    # The Orda house still needs re-pointing — that is what realign_profile is
    # for, and it is the whole remaining job now that the year is a label.
    realign_profile(student.user)
    with school_scope(b):
        Student._base_manager.get(pk=student.pk).save()  # must not raise

    student.refresh_from_db()
    assert student.intake_year == '2024/2025'


def test_it_is_out_of_the_tenancy_consistency_check():
    assert 'academic_year' not in Student.SCHOOL_CONSISTENT_FIELDS
    assert 'intake_year' not in Student.SCHOOL_CONSISTENT_FIELDS


def test_a_student_whose_school_has_no_year_gets_a_blank_rather_than_an_error():
    """The FK was nullable for this case; a blank string is the same answer."""
    a = f.SchoolFactory(slug='a')
    with school_scope(a):
        student = f.StudentFactory(user=f.StudentUserFactory(school=a))

    assert student.intake_year == ''
