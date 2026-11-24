"""GET students/<user_id>/overview/ (spec 0019): shape, numbers, access."""
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import PsychologicalState
from apps.home.models import Enrollment, HomeroomTeacherAssignment, QuarterGrade
from apps.lesson.models import SubjectSchedule
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory, EnrollmentFactory,
    HomeworkFactory, HomeworkGradeFactory, ParentFactory, ScheduleAttendanceFactory,
    ScheduleSessionFactory, SubjectOfferingFactory,
    SubjectScheduleFactory, SupervisorUserFactory, TeacherFactory,
    TeachingAssignmentFactory, UserFactory,
)

TODAY = timezone.localdate()


@pytest.fixture
def klass(academic_year):
    """A class of three: the student under test and two classmates."""
    class_group = ClassGroupFactory(academic_year=academic_year)
    student = EnrollmentFactory(class_group=class_group).student
    mate_a = EnrollmentFactory(class_group=class_group).student
    mate_b = EnrollmentFactory(class_group=class_group).student
    maths = SubjectOfferingFactory(class_group=class_group)
    physics = SubjectOfferingFactory(class_group=class_group)
    return {
        'class_group': class_group, 'student': student,
        'mates': (mate_a, mate_b), 'maths': maths, 'physics': physics,
    }


def url(student, **params):
    base = reverse('home-api:student-overview', args=[student.user_id])
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    return f'{base}?{query}' if query else base


def get(authenticated_client, student, user=None, active_role=None, **params):
    client = authenticated_client(user or AdminUserFactory(), active_role)
    return client.get(url(student, **params))


def grade(student, offering, quarter, value):
    QuarterGrade.objects.create(student=student, offering=offering, quarter=quarter, grade=value)


def attend(student, offering, quarter, day, status):
    # One schedule per offering and quarter, and one weekly slot in it.
    schedule = SubjectSchedule.objects.filter(offering=offering, quarter=quarter).first() \
        or SubjectScheduleFactory(offering=offering, quarter=quarter)
    session = schedule.sessions.first() or ScheduleSessionFactory(schedule=schedule)
    ScheduleAttendanceFactory(student=student, session=session, date=day, status=status)


def homeroom_teacher(class_group):
    teacher = TeacherFactory()
    teacher.user.groups.add(Group.objects.get_or_create(name='HomeroomTeacher')[0])
    HomeroomTeacherAssignment.objects.create(teacher=teacher, class_group=class_group)
    return teacher.user


# ── Shape and defaults ──

def test_ac1_overview_returns_contract_keys_for_quarter(klass, authenticated_client):
    response = get(authenticated_client, klass['student'], quarter=2)

    assert response.status_code == 200, response.data
    assert set(response.data) == {
        'student_id', 'quarter', 'grades', 'attendance', 'homework',
        'wellbeing', 'attention',
    }
    assert response.data['quarter'] == 2
    assert response.data['student_id'] == klass['student'].user_id


def test_ac2_default_quarter_is_current_or_last_ended(
    klass, academic_year, authenticated_client,
):
    academic_year.q2_start, academic_year.q2_end = TODAY - timedelta(30), TODAY - timedelta(2)
    academic_year.q3_start, academic_year.q3_end = TODAY - timedelta(1), TODAY + timedelta(30)
    academic_year.save()
    assert get(authenticated_client, klass['student']).data['quarter'] == 3

    academic_year.q3_start = TODAY + timedelta(1)
    academic_year.save()
    assert get(authenticated_client, klass['student']).data['quarter'] == 2


@pytest.mark.parametrize('quarter', ['5', '0', 'abc'])
def test_ac3_invalid_quarter_is_400(klass, authenticated_client, quarter):
    assert get(authenticated_client, klass['student'], quarter=quarter).status_code == 400


def test_ac4_empty_student_returns_nulls_and_zeros(klass, authenticated_client):
    data = get(authenticated_client, klass['student'], quarter=1).data

    assert data['grades'] == {
        'average': None, 'class_average': None, 'previous_quarter_average': None,
        'by_quarter': [
            {'quarter': q, 'average': None, 'class_average': None} for q in (1, 2, 3, 4)
        ],
    }
    assert data['attendance'] == {
        'rate': None, 'class_rate': None, 'present': 0, 'late': 0, 'absent': 0, 'total': 0,
    }
    assert data['homework'] == {'overdue': 0, 'pending': 0, 'submitted': 0, 'total': 0}
    assert data['wellbeing'] == {'latest': None}
    assert data['attention'] == []


# ── Grades ──

def test_ac5_average_and_class_average_for_quarter(klass, authenticated_client):
    s, (a, _), maths, physics = klass['student'], klass['mates'], klass['maths'], klass['physics']
    grade(s, maths, 2, 5)
    grade(s, physics, 2, 4)       # student avg 4.5
    grade(a, maths, 2, 3)         # mate a avg 3.0 (one subject only)
    # mate b has no marks in Q2 and sits out of the class average.

    grades = get(authenticated_client, s, quarter=2).data['grades']

    assert grades['average'] == 4.5
    assert grades['class_average'] == 3.8   # mean(4.5, 3.0) = 3.75


def test_ac6_previous_quarter_average_null_in_q1(klass, authenticated_client):
    s, maths = klass['student'], klass['maths']
    grade(s, maths, 1, 4)
    grade(s, maths, 2, 3)

    assert get(authenticated_client, s, quarter=2).data['grades']['previous_quarter_average'] == 4.0
    assert get(authenticated_client, s, quarter=1).data['grades']['previous_quarter_average'] is None


def test_ac7_by_quarter_always_four_entries(klass, authenticated_client):
    s = klass['student']
    grade(s, klass['maths'], 3, 5)

    by_quarter = get(authenticated_client, s, quarter=1).data['grades']['by_quarter']

    assert [e['quarter'] for e in by_quarter] == [1, 2, 3, 4]
    assert by_quarter[2] == {'quarter': 3, 'average': 5.0, 'class_average': 5.0}
    assert by_quarter[0]['average'] is None


def test_ac8_class_average_excludes_unenrolled_students(klass, authenticated_client):
    s, maths = klass['student'], klass['maths']
    leaver = EnrollmentFactory(class_group=klass['class_group']).student
    grade(s, maths, 1, 5)
    grade(leaver, maths, 1, 2)
    Enrollment.objects.filter(student=leaver).update(status='withdrawn')

    assert get(authenticated_client, s, quarter=1).data['grades']['class_average'] == 5.0


# ── Attendance, homework, wellbeing ──

def test_ac9_attendance_counts_rates_and_late_zero(klass, authenticated_client):
    s, (a, _), maths = klass['student'], klass['mates'], klass['maths']
    for offset, status in enumerate(['present', 'present', 'present', 'absent']):
        attend(s, maths, 1, TODAY - timedelta(10 - offset), status)
    attend(a, maths, 1, TODAY - timedelta(5), 'present')
    attend(s, maths, 2, TODAY - timedelta(1), 'absent')   # other quarter

    attendance = get(authenticated_client, s, quarter=1).data['attendance']

    assert attendance == {
        'rate': 75.0, 'class_rate': 80.0,
        'present': 3, 'late': 0, 'absent': 1, 'total': 4,
    }


def test_ac10_homework_graded_counts_as_submitted(klass, authenticated_client):
    s, maths = klass['student'], klass['maths']

    def hw(due, quarter=1):
        return HomeworkFactory(offering=maths, quarter=quarter, due_date=due)

    HomeworkGradeFactory(homework=hw(TODAY - timedelta(3)), student=s, grade=8)  # submitted, past due
    hw(TODAY - timedelta(1))                                                     # overdue
    HomeworkGradeFactory(homework=hw(TODAY - timedelta(2)), student=s, grade=None)  # overdue, ungraded row
    hw(TODAY + timedelta(3))                                                     # pending
    hw(TODAY - timedelta(1), quarter=2)                                          # other quarter

    homework = get(authenticated_client, s, quarter=1).data['homework']

    assert homework == {'submitted': 1, 'overdue': 2, 'pending': 1, 'total': 4}


def test_ac11_wellbeing_latest_ignores_soft_deleted(klass, authenticated_client):
    s = klass['student']
    older = PsychologicalState.objects.create(student=s, name='Mood', score=4)
    newest = PsychologicalState.objects.create(student=s, name='Sleep', score=1)
    PsychologicalState.objects.filter(pk=older.pk).update(time_added=timezone.now() - timedelta(days=2))
    newest.delete()

    latest = get(authenticated_client, s, quarter=1).data['wellbeing']['latest']

    assert latest['name'] == 'Mood'
    assert latest['score'] == 4
    assert set(latest) == {'name', 'score', 'time_added'}


def test_attention_flags_reach_the_response(klass, authenticated_client):
    s, maths = klass['student'], klass['maths']
    grade(s, maths, 1, 4)
    grade(s, maths, 2, 2)

    attention = get(authenticated_client, s, quarter=2).data['attention']

    assert [(f['code'], f['severity'], f['subject_id']) for f in attention] == [
        ('low_grade', 'critical', maths.subject_id),
        ('falling_grade', 'warning', maths.subject_id),
    ]
    assert attention[1]['params'] == {'from': 4, 'to': 2}


# ── Permissions ──

@pytest.mark.parametrize('make_user', [
    lambda klass: AdminUserFactory(),
    lambda klass: SupervisorUserFactory(),
    lambda klass: UserFactory(group_name='Principal'),
    lambda klass: UserFactory(group_name='Psychologist'),
    lambda klass: homeroom_teacher(klass['class_group']),
], ids=['admin', 'supervisor', 'principal', 'psychologist', 'homeroom'])
def test_ac20_admin_roles_psychologist_and_homeroom_get_200(
    klass, authenticated_client, make_user,
):
    response = get(authenticated_client, klass['student'], make_user(klass), quarter=1)
    assert response.status_code == 200, response.data


def test_ac20a_student_cannot_read_own_overview(klass, authenticated_client):
    s = klass['student']
    assert get(authenticated_client, s, s.user, quarter=1).status_code == 403


def test_ac21_parent_own_child_only(klass, authenticated_client):
    parent = ParentFactory()
    parent.students.add(klass['student'])

    assert get(authenticated_client, klass['student'], parent.user, quarter=1).status_code == 200
    assert get(authenticated_client, klass['mates'][0], parent.user, quarter=1).status_code == 403


def test_ac22_other_student_403_anonymous_401(klass, authenticated_client):
    other = klass['mates'][0]
    assert get(authenticated_client, klass['student'], other.user, quarter=1).status_code == 403
    # A fresh client: the shared api_client keeps the credentials set above.
    assert APIClient().get(url(klass['student'])).status_code == 401


def test_ac22a_subject_teacher_gets_403(klass, authenticated_client):
    ta = TeachingAssignmentFactory(offering=klass['maths'])
    assert get(authenticated_client, klass['student'], ta.teacher.user, quarter=1).status_code == 403


def test_ac22b_other_class_or_past_year_homeroom_gets_403(
    klass, academic_year, authenticated_client,
):
    other_class = homeroom_teacher(ClassGroupFactory(academic_year=academic_year))
    assert get(authenticated_client, klass['student'], other_class, quarter=1).status_code == 403

    past_year = AcademicYearFactory(is_active=False)
    past_class = ClassGroupFactory(academic_year=past_year)
    EnrollmentFactory(student=klass['student'], class_group=past_class)
    past_homeroom = homeroom_teacher(past_class)
    assert get(authenticated_client, klass['student'], past_homeroom, quarter=1).status_code == 403


def test_ac22c_homeroom_with_non_teacher_active_role_gets_403(klass, authenticated_client):
    user = homeroom_teacher(klass['class_group'])
    user.groups.add(Group.objects.get_or_create(name='Parent')[0])
    ParentFactory(user=user)   # a parent, but not of this student

    response = get(authenticated_client, klass['student'], user, 'parent', quarter=1)

    assert response.status_code == 403
    assert get(authenticated_client, klass['student'], user, 'teacher', quarter=1).status_code == 200


def test_ac23_unknown_user_id_is_404(authenticated_client, academic_year):
    client = authenticated_client(AdminUserFactory())
    response = client.get(reverse('home-api:student-overview', args=[999999]))
    assert response.status_code == 404


# ── Non-functional ──

def test_overview_query_count_is_bounded(klass, authenticated_client):
    s = klass['student']
    for offering in (klass['maths'], klass['physics'], SubjectOfferingFactory(
        class_group=klass['class_group'],
    )):
        grade(s, offering, 1, 4)
        grade(s, offering, 2, 3)
        attend(s, offering, 2, TODAY - timedelta(offering.id % 20 + 1), 'absent')
        HomeworkFactory(offering=offering, quarter=2, due_date=TODAY - timedelta(1))
    PsychologicalState.objects.create(student=s, name='Mood', score=2)
    client = authenticated_client(AdminUserFactory())

    with CaptureQueriesContext(connection) as queries:
        response = client.get(url(s, quarter=2))

    assert response.status_code == 200
    # Spec 0019: at most 15 queries for the overview itself, whatever the
    # number of subjects (13 measured), plus the user, their groups and the
    # student lookup (3).
    assert len(queries) <= 18, [q['sql'] for q in queries]
