"""
Tests for the split between the two assignment lists.

GET subject-assignments/ answers "what did I set" — the offerings the caller
teaches, nothing else. GET my-class/subject-assignments/ answers "what is my
homeroom class being given" — every subject taught to that class group, and
none of the caller's own work for their other classes. The pair is only useful
if neither leaks into the other, which is what the two list tests pin down.
"""

import pytest
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment
from core.factories import (
    AcademicYearFactory, ClassGroupFactory, StudentFactory,
    SubjectAssignmentFactory, SubjectFactory, SubjectOfferingFactory,
    TeacherFactory, TeachingAssignmentFactory,
)

TAUGHT_URL = reverse('home-api:subject-assignment-list-create')
HOMEROOM_URL = reverse('home-api:homeroom-subject-assignment-list')


@pytest.fixture
def cohort(db):
    """
    One teacher, homeroom teacher of 7A and teaching maths in both 7A and 7B.

      7A maths    taught by them, in their homeroom class  -> both lists
      7A physics  a colleague's, in their homeroom class   -> homeroom list only
      7B maths    taught by them, another class            -> taught list only
    """
    academic_year = AcademicYearFactory(is_active=True)
    homeroom_class = ClassGroupFactory(academic_year=academic_year, letter='A')
    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')

    maths = SubjectFactory(name='Mathematics')
    teacher = TeacherFactory()

    def offering(subject, class_group):
        return SubjectOfferingFactory(
            subject=subject, class_group=class_group,
            academic_year=academic_year,
        )

    homeroom_maths = offering(maths, homeroom_class)
    homeroom_physics = offering(SubjectFactory(name='Physics'), homeroom_class)
    other_maths = offering(maths, other_class)

    TeachingAssignmentFactory(teacher=teacher, offering=homeroom_maths)
    TeachingAssignmentFactory(teacher=teacher, offering=other_maths)
    TeachingAssignmentFactory(teacher=TeacherFactory(), offering=homeroom_physics)

    HomeroomTeacherAssignment.objects.create(
        teacher=teacher, class_group=homeroom_class, academic_year=academic_year,
    )

    return {
        'academic_year': academic_year,
        'teacher': teacher,
        'homeroom_class': homeroom_class,
        'homeroom_maths': SubjectAssignmentFactory(
            offering=homeroom_maths, title='7A maths quiz',
        ),
        'homeroom_physics': SubjectAssignmentFactory(
            offering=homeroom_physics, title='7A physics test', category='exam',
        ),
        'other_maths': SubjectAssignmentFactory(
            offering=other_maths, title='7B maths quiz',
        ),
    }


def titles(response):
    return {row['title'] for row in response.data['results']}


class TestTaughtAssignments:
    def test_teacher_sees_only_offerings_they_teach(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(TAUGHT_URL)

        assert response.status_code == 200
        assert titles(response) == {'7A maths quiz', '7B maths quiz'}

    def test_homeroom_class_alone_does_not_grant_access(self, cohort, authenticated_client):
        """A colleague's subject in the homeroom class is 404 on the detail route."""
        client = authenticated_client(cohort['teacher'].user)
        url = reverse(
            'home-api:subject-assignment-detail',
            args=[cohort['homeroom_physics'].id],
        )

        assert client.get(url).status_code == 404


class TestHomeroomAssignments:
    def test_returns_every_subject_of_the_homeroom_class(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(HOMEROOM_URL)

        assert response.status_code == 200
        assert titles(response) == {'7A maths quiz', '7A physics test'}

    def test_filters_apply(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(HOMEROOM_URL, {'category': 'exam'})

        assert titles(response) == {'7A physics test'}

    def test_teacher_without_homeroom_gets_empty_list(self, cohort, authenticated_client):
        client = authenticated_client(TeacherFactory().user)
        response = client.get(HOMEROOM_URL)

        assert response.status_code == 200
        assert response.data['results'] == []

    def test_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(StudentFactory().user)
        assert client.get(HOMEROOM_URL).status_code == 403

    def test_anonymous_is_401(self, cohort, api_client):
        assert api_client.get(HOMEROOM_URL).status_code == 401
