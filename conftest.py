import pytest
from rest_framework.test import APIClient

from core.factories import (
    UserFactory, StudentFactory, TeacherFactory, ParentFactory,
    SupervisorFactory, AdminUserFactory, AcademicYearFactory,
    ClassGroupFactory, SchoolGroupFactory, EnrollmentFactory,
    SubjectFactory, SubjectOfferingFactory, TeachingAssignmentFactory,
    LessonFactory, TopicFactory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def academic_year(db):
    return AcademicYearFactory(is_active=True)


@pytest.fixture
def class_group(academic_year):
    return ClassGroupFactory(academic_year=academic_year)


@pytest.fixture
def school_group(db):
    return SchoolGroupFactory()


@pytest.fixture
def admin_user(db):
    return AdminUserFactory()


@pytest.fixture
def teacher(academic_year):
    return TeacherFactory()


@pytest.fixture
def student(academic_year, school_group):
    return StudentFactory(
        school_group=school_group,
        academic_year=academic_year,
    )


@pytest.fixture
def parent(db):
    return ParentFactory()


@pytest.fixture
def supervisor(db):
    return SupervisorFactory()


@pytest.fixture
def authenticated_client(api_client):
    """Returns a function that authenticates the client as a given user."""
    def _auth(user):
        api_client.force_authenticate(user=user)
        return api_client
    return _auth


@pytest.fixture
def subject(db):
    return SubjectFactory()


@pytest.fixture
def offering(class_group, subject):
    return SubjectOfferingFactory(
        subject=subject,
        class_group=class_group,
        academic_year=class_group.academic_year,
    )


@pytest.fixture
def enrollment(student, class_group):
    return EnrollmentFactory(
        student=student,
        class_group=class_group,
        academic_year=class_group.academic_year,
    )


@pytest.fixture
def teaching_assignment(teacher, offering):
    return TeachingAssignmentFactory(
        teacher=teacher,
        offering=offering,
    )


@pytest.fixture
def lesson(offering):
    return LessonFactory(offering=offering)


@pytest.fixture
def topics(lesson):
    """Create 3 topics with weights summing to 100."""
    t1 = TopicFactory(lesson=lesson, title='Topic A', weight=40, order=0)
    t2 = TopicFactory(lesson=lesson, title='Topic B', weight=30, order=1)
    t3 = TopicFactory(lesson=lesson, title='Topic C', weight=30, order=2)
    return [t1, t2, t3]
