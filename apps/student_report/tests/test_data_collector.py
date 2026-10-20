"""The data collector that feeds report generation.

Regression cover for every report failing with "Invalid field name(s) given in
select_related: 'academic_year'": `Student.academic_year` became the
`intake_year` label in `authentication/0043`, but the collector still asked to
join it, so `collect_student_data` raised before reading a single grade.
"""

import pytest

from apps.student_report.services.data_collector import collect_student_data
from core.factories import AcademicYearFactory, StudentFactory
from core.tenancy import school_scope


@pytest.mark.django_db
def test_collect_student_data_runs_for_a_student_without_a_year_relation():
    student = StudentFactory()
    with school_scope(student.user.school):
        year = AcademicYearFactory()
        data = collect_student_data(student_id=student.pk, quarter=1)

    assert data['personal']['full_name'] == (
        student.user.get_full_name() or student.user.username
    )
    assert data['personal']['academic_year'] == str(year)
