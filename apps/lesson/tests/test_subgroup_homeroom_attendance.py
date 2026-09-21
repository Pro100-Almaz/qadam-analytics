"""
A подгруппа has no homeroom teacher of its own.

For schedules, sessions and attendance it inherits the homeroom teacher of the
class whose constellation holds it: the homeroom teacher of 7A reaches 7A's
subgroups on the same terms as 7A itself.
"""

import pytest
from django.urls import reverse

from apps.home.models import (
    ClassGroupCollection, Enrollment, HomeroomTeacherAssignment,
)
from core.factories import (
    ClassGroupFactory, MinorClassGroupFactory, ScheduleSessionFactory,
    StudentFactory, SubjectFactory, SubjectOfferingFactory,
    SubjectScheduleFactory, TeacherFactory,
)


SCHEDULES_URL = reverse('lesson-api:subject-schedule-list-create')


def attendance_url(session):
    return reverse('lesson-api:schedule-attendance-list-create', args=[session.id])


def timetable_for(class_group, subject_name):
    """An offering of `subject_name` for a class group, scheduled with one slot."""
    offering = SubjectOfferingFactory(
        subject=SubjectFactory(name=subject_name), class_group=class_group,
    )
    schedule = SubjectScheduleFactory(offering=offering, quarter=1)
    session = ScheduleSessionFactory(schedule=schedule, weekday=0)
    return schedule, session


@pytest.fixture
def cohort(academic_year):
    """7A with a homeroom teacher and a subgroup; 7B with a subgroup of its own."""
    class_a = ClassGroupFactory(academic_year=academic_year, letter='A')
    class_b = ClassGroupFactory(academic_year=academic_year, letter='B')

    homeroom = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(teacher=homeroom, class_group=class_a)

    english = MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')
    chess = MinorClassGroupFactory(academic_year=academic_year, letter='Шахматы')
    ClassGroupCollection.bind_minor_groups(class_a, [english])
    ClassGroupCollection.bind_minor_groups(class_b, [chess])

    student = StudentFactory()
    Enrollment.enroll_student(student, class_a)
    Enrollment.enroll_student(student, english)

    own_schedule, own_session = timetable_for(class_a, 'Математика')
    english_schedule, english_session = timetable_for(english, 'English')
    chess_schedule, chess_session = timetable_for(chess, 'Шахматы')

    return {
        'homeroom': homeroom,
        'class_a': class_a,
        'english': english,
        'chess': chess,
        'student': student,
        'own_schedule': own_schedule,
        'english_schedule': english_schedule,
        'english_session': english_session,
        'chess_schedule': chess_schedule,
        'chess_session': chess_session,
    }


@pytest.fixture
def homeroom_client(cohort, authenticated_client):
    return authenticated_client(cohort['homeroom'].user)


# ── Reading schedules: only_mine ──

def listed_ids(response):
    return {row['id'] for row in response.data['results']}


MINE = {'only_mine': 'true'}


def test_homeroom_teacher_sees_the_subgroup_schedule(homeroom_client, cohort):
    response = homeroom_client.get(SCHEDULES_URL, MINE)

    assert cohort['english_schedule'].id in listed_ids(response)
    assert cohort['own_schedule'].id in listed_ids(response)


def test_another_class_subgroup_stays_out_of_my_timetable(homeroom_client, cohort):
    response = homeroom_client.get(SCHEDULES_URL, MINE)

    assert cohort['chess_schedule'].id not in listed_ids(response)


def test_an_unbound_subgroup_stays_out_of_my_timetable(
    homeroom_client, cohort, academic_year
):
    loose = MinorClassGroupFactory(academic_year=academic_year, letter='Хор')
    loose_schedule, _ = timetable_for(loose, 'Хор')

    response = homeroom_client.get(SCHEDULES_URL, MINE)

    assert loose_schedule.id not in listed_ids(response)


def test_unbinding_the_subgroup_takes_it_out_of_my_timetable(homeroom_client, cohort):
    ClassGroupCollection.bind_minor_groups(cohort['class_a'], [])

    response = homeroom_client.get(SCHEDULES_URL, MINE)

    assert cohort['english_schedule'].id not in listed_ids(response)


def test_only_mine_leaves_a_teacher_without_classes_empty_handed(
    cohort, authenticated_client
):
    outsider = authenticated_client(TeacherFactory().user)

    response = outsider.get(SCHEDULES_URL, MINE)

    assert response.data['results'] == []


# ── Reading schedules: the staff-wide default ──

def test_any_teacher_reads_the_whole_timetable_by_default(cohort, authenticated_client):
    outsider = authenticated_client(TeacherFactory().user)

    response = outsider.get(SCHEDULES_URL)

    assert listed_ids(response) == {
        cohort['own_schedule'].id,
        cohort['english_schedule'].id,
        cohort['chess_schedule'].id,
    }


def test_the_default_covers_a_class_and_its_subgroups(cohort, authenticated_client):
    outsider = authenticated_client(TeacherFactory().user)

    response = outsider.get(SCHEDULES_URL, {
        'class_group': cohort['class_a'].id, 'include_minor_groups': 'true',
    })

    assert listed_ids(response) == {
        cohort['own_schedule'].id, cohort['english_schedule'].id,
    }


def test_a_student_is_not_widened_by_the_default(cohort, authenticated_client):
    client = authenticated_client(cohort['student'].user)

    response = client.get(SCHEDULES_URL)

    # Their own class and the subgroup they are enrolled in — not 7B's.
    assert listed_ids(response) == {
        cohort['own_schedule'].id, cohort['english_schedule'].id,
    }


def test_reading_widely_does_not_grant_writing(cohort, authenticated_client):
    outsider_teacher = TeacherFactory()
    outsider = authenticated_client(outsider_teacher.user)

    assert cohort['own_schedule'].id in listed_ids(outsider.get(SCHEDULES_URL))
    assert outsider.post(
        attendance_url(cohort['english_session']),
        attendance_payload(cohort['student']),
    ).status_code == 403


# ── Recording attendance ──

def attendance_payload(student):
    return {'student': student.id, 'date': '2025-09-01', 'status': 'present'}


def test_homeroom_teacher_may_record_subgroup_attendance(homeroom_client, cohort):
    response = homeroom_client.post(
        attendance_url(cohort['english_session']),
        attendance_payload(cohort['student']),
    )

    assert response.status_code == 201
    assert response.data['status'] == 'present'


def test_homeroom_teacher_may_not_record_another_class_subgroup(homeroom_client, cohort):
    other_student = StudentFactory()
    Enrollment.enroll_student(other_student, cohort['chess'])

    response = homeroom_client.post(
        attendance_url(cohort['chess_session']), attendance_payload(other_student),
    )

    assert response.status_code == 403


def test_recording_stops_when_the_subgroup_is_unbound(homeroom_client, cohort):
    ClassGroupCollection.bind_minor_groups(cohort['class_a'], [])

    response = homeroom_client.post(
        attendance_url(cohort['english_session']),
        attendance_payload(cohort['student']),
    )

    assert response.status_code == 403


def test_an_outside_teacher_may_not_record_subgroup_attendance(
    cohort, authenticated_client
):
    outsider = authenticated_client(TeacherFactory().user)

    response = outsider.post(
        attendance_url(cohort['english_session']),
        attendance_payload(cohort['student']),
    )

    assert response.status_code == 403
