"""
The per-student analytics resolve a student's *class*, never a подгруппа.

A student holds one active enrollment in their class and one more per subgroup
they join. The three per-student endpoints each look that enrollment up to
decide which class group — and therefore which subjects — the report covers, so
they have to ask for the major one by category. Taking whichever enrollment
comes first silently narrows the whole report to a single subgroup: the class's
own subjects disappear.

The subgroup is created before the class in every fixture here on purpose. The
default ordering ends in `class_group`, so the lower id wins a `.first()` — that
is exactly the case that used to break.
"""

import pytest
from django.urls import reverse

from apps.home.models import ClassGroupCollection, Enrollment
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory, GradeLevelFactory,
    MinorClassGroupFactory, StudentFactory, SubjectAssignmentFactory,
    SubjectFactory, SubjectGradeFactory, SubjectOfferingFactory,
)


@pytest.fixture
def enrolled_both_ways(db):
    """A student in 7A and in «English Advanced», a подгруппа bound to 7A."""
    academic_year = AcademicYearFactory(
        is_active=True, q1_start='2025-09-01', q1_end='2025-10-31',
    )
    subgroup = MinorClassGroupFactory(
        academic_year=academic_year, letter='English Advanced',
    )
    class_group = ClassGroupFactory(
        academic_year=academic_year,
        grade_level=GradeLevelFactory(number=7),
        letter='A',
    )
    ClassGroupCollection.bind_minor_groups(class_group, [subgroup])
    assert subgroup.id < class_group.id  # the ordering trap this guards

    student = StudentFactory(academic_year=academic_year)
    Enrollment.enroll_student(student, class_group)
    Enrollment.enroll_student(student, subgroup)

    maths = SubjectOfferingFactory(
        subject=SubjectFactory(name='Mathematics'), class_group=class_group,
    )
    physics = SubjectOfferingFactory(
        subject=SubjectFactory(name='Physics'), class_group=class_group,
    )
    english = SubjectOfferingFactory(
        subject=SubjectFactory(name='English'), class_group=subgroup,
    )
    for offering in (maths, physics, english):
        assignment = SubjectAssignmentFactory(
            offering=offering, max_grade=100, date='2025-09-15',
        )
        SubjectGradeFactory(assignment=assignment, student=student, grade=80)

    return {
        'academic_year': academic_year,
        'class_group': class_group,
        'subgroup': subgroup,
        'student': student,
    }


@pytest.fixture
def admin_api_client(db, authenticated_client):
    return authenticated_client(AdminUserFactory())


def test_assignment_summary_reports_the_class_not_the_subgroup(
    admin_api_client, enrolled_both_ways,
):
    response = admin_api_client.get(reverse(
        'lesson-api:analytics-assignment-summary',
        args=[enrolled_both_ways['student'].id],
    ))

    assert response.status_code == 200
    assert response.data['class_group']['id'] == enrolled_both_ways['class_group'].id
    assert [axis['subject'] for axis in response.data['axes']] == [
        'Mathematics', 'Physics',
    ]


def test_subject_radar_reports_the_class_not_the_subgroup(
    admin_api_client, enrolled_both_ways,
):
    response = admin_api_client.get(reverse(
        'lesson-api:analytics-subject-radar',
        args=[enrolled_both_ways['student'].id],
    ))

    assert response.status_code == 200
    assert response.data['class_group'] == str(enrolled_both_ways['class_group'])
    assert [axis['subject'] for axis in response.data['axes']] == [
        'Mathematics', 'Physics',
    ]


def test_attendance_summary_reports_the_class_not_the_subgroup(
    admin_api_client, enrolled_both_ways,
):
    response = admin_api_client.get(reverse(
        'lesson-api:analytics-attendance-summary',
        args=[enrolled_both_ways['student'].id],
    ))

    assert response.status_code == 200
    assert response.data['class_group']['id'] == enrolled_both_ways['class_group'].id


def test_a_student_with_only_a_subgroup_has_no_class_to_report(
    admin_api_client, enrolled_both_ways,
):
    """Dropping the class enrollment leaves the subgroup — and no class."""
    Enrollment.objects.filter(
        student=enrolled_both_ways['student'],
        class_group=enrolled_both_ways['class_group'],
    ).delete()

    response = admin_api_client.get(reverse(
        'lesson-api:analytics-assignment-summary',
        args=[enrolled_both_ways['student'].id],
    ))

    assert response.status_code == 200
    assert response.data['class_group'] is None
    assert response.data['axes'] == []
