"""Spec 0013, AC-10 — home-side read paths leave soft-deleted children out.

See apps/lesson/tests/test_soft_delete_read_paths.py for the rule: each site
that joins from a live parent into a soft-deletable child got an explicit
`is_deleted=False`, and each one has a test here with one deleted child.
"""

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.urls import reverse

from apps.authentication.models import Student
from apps.home.api.views.assignments import (
    grade_queryset as subject_grade_queryset, homeroom_grade_queryset,
)
from apps.home.api.views.quarter_grades import homeroom_quarter_grade_queryset
from apps.home.models import (
    AcademicYear, AssignmentCategory, ClassGroup, HomeroomTeacherAssignment,
    QuarterGrade,
)
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory,
    EnrollmentFactory, ParentFactory, SubjectAssignmentFactory,
    SubjectGradeFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory, UserFactory,
)

pytestmark = pytest.mark.django_db


def _admin_request(path):
    request = RequestFactory().get(path)
    request.user = AdminUserFactory(is_superuser=True, is_staff=True)
    return request


@pytest.fixture
def homeroom():
    """A homeroom teacher, their class, and a student enrolled in it.

    Returns the enrollment so a test can delete it, and an offering in that
    class the homeroom teacher does NOT teach: only the homeroom branch of a
    queryset, which joins through the enrollment, can reach its rows.
    """
    teacher = TeacherFactory()
    teacher.user.groups.add(Group.objects.get_or_create(name='HomeroomTeacher')[0])
    class_group = ClassGroupFactory()
    HomeroomTeacherAssignment.objects.create(teacher=teacher, class_group=class_group)
    enrollment = EnrollmentFactory(class_group=class_group)
    offering = SubjectOfferingFactory(class_group=class_group)
    return teacher, enrollment, offering


def test_ac10_subject_grade_homeroom_branch_excludes_deleted_enrollment(homeroom):
    teacher, enrollment, offering = homeroom
    grade = SubjectGradeFactory(
        student=enrollment.student, assignment__offering=offering,
    )
    assert subject_grade_queryset(teacher.user).filter(pk=grade.pk).exists()

    enrollment.delete()

    assert not subject_grade_queryset(teacher.user).filter(pk=grade.pk).exists()


def test_ac10_homeroom_grades_exclude_deleted_enrollment(homeroom):
    teacher, enrollment, offering = homeroom
    grade = SubjectGradeFactory(
        student=enrollment.student, assignment__offering=offering,
    )
    assert homeroom_grade_queryset(teacher.user).filter(pk=grade.pk).exists()

    enrollment.delete()

    assert not homeroom_grade_queryset(teacher.user).filter(pk=grade.pk).exists()


def test_ac10_homeroom_quarter_grades_exclude_deleted_enrollment(homeroom):
    teacher, enrollment, offering = homeroom
    grade = QuarterGrade.objects.create(
        student=enrollment.student, offering=offering, quarter=1, grade=5,
    )
    assert homeroom_quarter_grade_queryset(teacher.user).filter(pk=grade.pk).exists()

    enrollment.delete()

    assert not homeroom_quarter_grade_queryset(teacher.user).filter(pk=grade.pk).exists()


def test_ac10_classmates_exclude_deleted_enrollment(authenticated_client):
    class_group = ClassGroupFactory()
    viewer = EnrollmentFactory(class_group=class_group).student
    EnrollmentFactory(class_group=class_group).delete()

    response = authenticated_client(viewer.user).get(
        reverse('home-api:student-classmates'),
    )

    assert response.status_code == 200
    assert response.data == []


def test_ac10_teacher_offerings_without_live_assignments_are_empty(
    authenticated_client,
):
    teaching = TeachingAssignmentFactory()
    SubjectAssignmentFactory(offering=teaching.offering).delete()

    response = authenticated_client(teaching.teacher.user).get(
        reverse('home-api:teacher-offering-list'), {'include_empty': 'false'},
    )

    assert response.status_code == 200, response.data
    assert response.data['offerings'] == []


def test_ac10_teacher_detail_parent_link_excludes_deleted_enrollment(
    authenticated_client,
):
    teaching = TeachingAssignmentFactory()
    enrollment = EnrollmentFactory(class_group=teaching.offering.class_group)
    parent = ParentFactory()
    parent.students.add(enrollment.student)
    url = reverse('home-api:teacher-detail', args=[teaching.teacher.user_id])
    assert authenticated_client(parent.user).get(url).status_code == 200

    enrollment.delete()

    assert authenticated_client(parent.user).get(url).status_code == 403


def test_ac10_assignment_category_admin_count_excludes_deleted_assignment():
    live = SubjectAssignmentFactory(category='lesson')
    SubjectAssignmentFactory(category=live.category).delete()

    category = admin.site._registry[AssignmentCategory].get_queryset(
        _admin_request('/admin/home/assignmentcategory/'),
    ).get(pk=live.category_id)

    assert category._assignment_count == 1


def test_ac10_class_group_admin_counts_exclude_deleted_children():
    class_group = ClassGroupFactory()
    EnrollmentFactory(class_group=class_group)
    EnrollmentFactory(class_group=class_group).delete()
    SubjectOfferingFactory(class_group=class_group)
    SubjectOfferingFactory(class_group=class_group).delete()

    row = admin.site._registry[ClassGroup].get_queryset(
        _admin_request('/admin/home/classgroup/'),
    ).get(pk=class_group.pk)

    assert row._students_count == 1
    assert row._offerings_count == 1


def test_ac10_intake_year_skips_deleted_academic_year():
    school = UserFactory().school
    AcademicYear._base_manager.filter(school=school).update(is_active=False)
    live = AcademicYearFactory(school=school, year='2030/2031', is_active=False)
    AcademicYearFactory(school=school, year='2031/2032', is_active=True).delete()

    student = Student.objects.create(user=UserFactory(school=school))

    assert student.intake_year == live.year
