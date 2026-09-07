"""GET /api/v1/class-groups/<id>/students/ — the roster of a class or подгруппа."""

import pytest
from django.urls import reverse

from apps.home.models import Enrollment
from core.factories import (
    AdminUserFactory, ClassGroupFactory, EnrollmentFactory, MinorClassGroupFactory,
    ParentFactory, StudentFactory, TeacherFactory,
)


def url_for(class_group_id):
    return reverse('home-api:class-group-students', args=[class_group_id])


@pytest.fixture
def admin_api_client(db, authenticated_client):
    return authenticated_client(AdminUserFactory())


@pytest.fixture
def major_a(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='A')


@pytest.fixture
def subgroup(academic_year):
    return MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')


@pytest.fixture
def roster(major_a):
    """Two active students, ordered by surname, plus one who left."""
    borisova = StudentFactory(user__first_name='Аружан', user__last_name='Борисова')
    aliyev = StudentFactory(user__first_name='Тимур', user__last_name='Алиев')
    departed = StudentFactory(user__first_name='Ерлан', user__last_name='Ушёл')

    EnrollmentFactory(student=aliyev, class_group=major_a, start_date='2025-09-01')
    EnrollmentFactory(student=borisova, class_group=major_a, start_date='2025-09-01')
    EnrollmentFactory(student=departed, class_group=major_a, status='transferred')

    return {'aliyev': aliyev, 'borisova': borisova, 'departed': departed}


def test_returns_the_active_students_by_surname(admin_api_client, major_a, roster):
    response = admin_api_client.get(url_for(major_a.id))

    assert response.status_code == 200
    assert [row['id'] for row in response.data] == [
        roster['aliyev'].id, roster['borisova'].id,
    ]


def test_row_carries_the_student_and_their_enrollment(admin_api_client, major_a, roster):
    row = admin_api_client.get(url_for(major_a.id)).data[0]
    enrollment = Enrollment.objects.get(student=roster['aliyev'], class_group=major_a)

    assert row['id'] == roster['aliyev'].id
    assert row['user']['first_name'] == 'Тимур'
    assert row['user']['last_name'] == 'Алиев'
    assert row['enrollment_id'] == enrollment.id
    assert row['status'] == 'active'
    assert row['start_date'] == '2025-09-01'
    assert row['end_date'] is None


def test_status_filter_takes_another_status(admin_api_client, major_a, roster):
    response = admin_api_client.get(url_for(major_a.id), {'status': 'transferred'})

    assert [row['id'] for row in response.data] == [roster['departed'].id]


def test_status_all_returns_every_enrollment(admin_api_client, major_a, roster):
    response = admin_api_client.get(url_for(major_a.id), {'status': 'all'})

    assert len(response.data) == 3


def test_an_unknown_status_is_a_400(admin_api_client, major_a):
    response = admin_api_client.get(url_for(major_a.id), {'status': 'nonsense'})

    assert response.status_code == 400
    assert 'status' in response.data


def test_a_subgroup_has_a_roster_of_its_own(admin_api_client, subgroup, major_a, student):
    Enrollment.enroll_student(student, major_a)
    Enrollment.enroll_student(student, subgroup)
    other = StudentFactory()
    Enrollment.enroll_student(other, major_a)

    response = admin_api_client.get(url_for(subgroup.id))

    assert [row['id'] for row in response.data] == [student.id]


def test_an_empty_class_returns_an_empty_list(admin_api_client, major_a):
    assert admin_api_client.get(url_for(major_a.id)).data == []


def test_unknown_class_group_is_a_404(admin_api_client):
    assert admin_api_client.get(url_for(9999)).status_code == 404


def test_anonymous_access_is_rejected(api_client, major_a):
    assert api_client.get(url_for(major_a.id)).status_code == 401


def test_a_teacher_may_read_any_roster(authenticated_client, major_a, roster):
    client = authenticated_client(TeacherFactory().user)

    assert len(client.get(url_for(major_a.id)).data) == 2


def test_a_student_reads_their_own_class(authenticated_client, major_a, roster):
    client = authenticated_client(roster['aliyev'].user)

    response = client.get(url_for(major_a.id))

    assert response.status_code == 200
    assert len(response.data) == 2


def test_a_student_cannot_read_another_class(
    authenticated_client, major_a, roster, academic_year
):
    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')
    client = authenticated_client(roster['aliyev'].user)

    assert client.get(url_for(other_class.id)).status_code == 403


def test_a_parent_reads_their_child_class(authenticated_client, major_a, roster):
    parent = ParentFactory()
    parent.students.add(roster['aliyev'])
    client = authenticated_client(parent.user)

    assert len(client.get(url_for(major_a.id)).data) == 2


def test_a_parent_cannot_read_an_unrelated_class(
    authenticated_client, major_a, roster, academic_year
):
    parent = ParentFactory()
    parent.students.add(roster['aliyev'])
    other_class = ClassGroupFactory(academic_year=academic_year, letter='B')
    client = authenticated_client(parent.user)

    assert client.get(url_for(other_class.id)).status_code == 403
