import pytest
from django.urls import reverse

from core.factories import (
    AdminUserFactory,
    ClassGroupFactory,
    ScheduleSessionFactory,
    SubjectFactory,
    SubjectOfferingFactory,
    SubjectScheduleFactory,
    TeacherFactory,
    TeachingAssignmentFactory,
)


CALENDAR_SUBJECTS_URL = reverse('lesson-api:calendar-subjects')
SUBJECT_SCHEDULES_URL = reverse('lesson-api:subject-schedule-list-create')
TEACHERS_URL = reverse('home-api:teacher-list')


@pytest.fixture
def schedule_data(academic_year):
    teacher = TeacherFactory(
        user__first_name='Zara',
        user__last_name='Assigned',
    )
    other_teacher = TeacherFactory(
        user__first_name='Other',
        user__last_name='Teacher',
    )

    class_group = ClassGroupFactory(academic_year=academic_year, letter='A')
    other_class_group = ClassGroupFactory(academic_year=academic_year, letter='B')
    subject = SubjectFactory(name='Mathematics')
    other_subject = SubjectFactory(name='Physics')

    offering = SubjectOfferingFactory(
        subject=subject,
        class_group=class_group,
        academic_year=academic_year,
    )
    other_offering = SubjectOfferingFactory(
        subject=other_subject,
        class_group=other_class_group,
        academic_year=academic_year,
    )

    TeachingAssignmentFactory(teacher=teacher, offering=offering, role='assistant')
    TeachingAssignmentFactory(teacher=other_teacher, offering=other_offering)

    matching = SubjectScheduleFactory(offering=offering, quarter=2)
    monday = ScheduleSessionFactory(
        schedule=matching,
        weekday=0,
        time_start='09:00',
        time_end='09:45',
    )
    wednesday = ScheduleSessionFactory(
        schedule=matching,
        weekday=2,
        time_start='11:00',
        time_end='11:45',
    )

    SubjectScheduleFactory(offering=offering, quarter=1)
    SubjectScheduleFactory(offering=other_offering, quarter=2)

    return {
        'teacher': teacher,
        'other_teacher': other_teacher,
        'matching': matching,
        'monday': monday,
        'wednesday': wednesday,
        'class_group': class_group,
        'subject': subject,
    }


def test_calendar_subjects_returns_teacher_quarter_schedules_with_sessions(
    schedule_data, authenticated_client,
):
    client = authenticated_client(AdminUserFactory())

    response = client.get(CALENDAR_SUBJECTS_URL, {
        'teacher': schedule_data['teacher'].id,
        'quarter': 2,
    })

    assert response.status_code == 200
    assert [row['id'] for row in response.data] == [schedule_data['matching'].id]

    row = response.data[0]
    assert row['type'] == 'subject'
    assert row['title'] == 'Mathematics'
    assert row['offering_id'] == schedule_data['matching'].offering_id
    assert row['class_group_id'] == schedule_data['class_group'].id
    assert row['class_group']['id'] == schedule_data['class_group'].id
    assert row['class_group']['letter'] == schedule_data['class_group'].letter
    assert row['quarter'] == 2
    assert [session['id'] for session in row['sessions']] == [
        schedule_data['monday'].id,
        schedule_data['wednesday'].id,
    ]
    assert row['sessions'][0]['weekday'] == 0
    assert row['sessions'][1]['weekday'] == 2


def test_subject_schedules_support_teacher_filter(schedule_data, authenticated_client):
    client = authenticated_client(AdminUserFactory())

    response = client.get(SUBJECT_SCHEDULES_URL, {
        'teacher': schedule_data['teacher'].id,
        'quarter': 2,
    })

    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [
        schedule_data['matching'].id,
    ]


def test_calendar_subjects_requires_teacher_and_quarter(authenticated_client):
    client = authenticated_client(AdminUserFactory())

    missing_teacher = client.get(CALENDAR_SUBJECTS_URL, {'quarter': 2})
    missing_quarter = client.get(CALENDAR_SUBJECTS_URL, {'teacher': 1})

    assert missing_teacher.status_code == 400
    assert missing_teacher.data['detail'] == 'teacher is required. Use a teacher profile id.'
    assert missing_quarter.status_code == 400
    assert missing_quarter.data['detail'] == 'quarter is required. Use 1, 2, 3, or 4.'


@pytest.mark.parametrize('quarter', ['0', '5', 'bad'])
def test_calendar_subjects_rejects_invalid_quarter(
    quarter, schedule_data, authenticated_client,
):
    client = authenticated_client(AdminUserFactory())

    response = client.get(CALENDAR_SUBJECTS_URL, {
        'teacher': schedule_data['teacher'].id,
        'quarter': quarter,
    })

    assert response.status_code == 400
    assert response.data['detail'] == 'Invalid quarter. Use 1, 2, 3, or 4.'


def test_teacher_list_is_deterministically_ordered(authenticated_client):
    zed = TeacherFactory(user__first_name='Zed', user__last_name='Brown')
    amy = TeacherFactory(user__first_name='Amy', user__last_name='Brown')
    cole = TeacherFactory(user__first_name='Cole', user__last_name='Adams')

    client = authenticated_client(AdminUserFactory())
    response = client.get(TEACHERS_URL)

    assert response.status_code == 200
    returned_ids = [row['id'] for row in response.data['results']]
    expected_order = [cole.id, amy.id, zed.id]
    assert returned_ids[:3] == expected_order
