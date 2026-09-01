"""
Tests for the three read-only attendance analytics endpoints.

The recurring theme is that an unrecorded slot is not an absence. Most of these
assert an exact rate that only comes out right if the divisor was the number of
rows that exist rather than the number of slots that might have existed — and
the heatmap tests assert the nulls that keep the two distinguishable.
"""

from datetime import time

import pytest
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory, EnrollmentFactory,
    ParentFactory, ScheduleAttendanceFactory, ScheduleSessionFactory,
    StudentFactory, SubjectFactory, SubjectOfferingFactory,
    SubjectScheduleFactory, TeacherFactory, TeachingAssignmentFactory,
)


def summary_url(student):
    return reverse('lesson-api:analytics-attendance-summary', args=[student.id])


def heatmap_url(offering):
    return reverse('lesson-api:analytics-attendance-heatmap', args=[offering.id])


def overview_url(class_group):
    return reverse(
        'lesson-api:analytics-attendance-overview', args=[class_group.id],
    )


@pytest.fixture
def cohort(db):
    """
    One class group, two subjects, four students, nine registered rows.

      s0  Monday 1st + Wednesday present, Wednesday physics absent  -> 3/4
      s1  present once in maths, absent twice, present in physics   -> 2/4
      s2  a single absence on the first day and nothing since       -> 0/1
      s3  never registered at all                                   -> 0/0

    s3 is the point of the fixture as much as the others: a student with no
    rows must not be counted as absent, and must not land on the at-risk list.
    """
    academic_year = AcademicYearFactory(is_active=True)
    class_group = ClassGroupFactory(academic_year=academic_year)

    maths = SubjectOfferingFactory(
        subject=SubjectFactory(name='Mathematics'),
        class_group=class_group,
        academic_year=academic_year,
    )
    physics = SubjectOfferingFactory(
        subject=SubjectFactory(name='Physics'),
        class_group=class_group,
        academic_year=academic_year,
    )

    students = []
    for index in range(4):
        student = StudentFactory(academic_year=academic_year)
        student.user.first_name = 'Student'
        student.user.last_name = f'Number{index}'
        student.user.save()
        EnrollmentFactory(
            student=student,
            class_group=class_group,
            academic_year=academic_year,
        )
        students.append(student)

    maths_schedule = SubjectScheduleFactory(offering=maths, quarter=1)
    monday = ScheduleSessionFactory(
        schedule=maths_schedule, weekday=0,
        time_start=time(9, 0), time_end=time(9, 45),
    )
    wednesday = ScheduleSessionFactory(
        schedule=maths_schedule, weekday=2,
        time_start=time(11, 0), time_end=time(11, 45),
    )

    physics_schedule = SubjectScheduleFactory(offering=physics, quarter=1)
    tuesday = ScheduleSessionFactory(
        schedule=physics_schedule, weekday=1,
        time_start=time(10, 0), time_end=time(10, 45),
    )

    def register(session, date, **statuses):
        for index, value in statuses.items():
            ScheduleAttendanceFactory(
                session=session,
                student=students[int(index[1:])],
                date=date,
                status=value,
            )

    register(monday, '2025-09-01', s0='present', s1='present', s2='absent')
    register(wednesday, '2025-09-03', s0='present', s1='absent')
    register(monday, '2025-09-08', s0='present', s1='absent')
    register(tuesday, '2025-09-02', s0='absent', s1='present')

    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=maths)

    return {
        'academic_year': academic_year,
        'class_group': class_group,
        'maths': maths,
        'physics': physics,
        'maths_schedule': maths_schedule,
        'monday': monday,
        'wednesday': wednesday,
        'students': students,
        'teacher': teacher,
    }


# ── Student summary ──

@pytest.mark.django_db
class TestStudentAttendanceSummary:

    def test_totals_count_only_registered_rows(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][0].user)
        response = client.get(summary_url(cohort['students'][0]))

        assert response.status_code == 200
        assert response.data['totals'] == {
            'recorded': 4, 'present': 3, 'absent': 1,
            'attendance_rate': pytest.approx(75.0),
        }
        assert response.data['counting']['unrecorded_as'] == 'excluded'

    def test_student_with_nothing_registered_reads_zero_with_zero_recorded(
        self, cohort, authenticated_client,
    ):
        """The rate is meaningless here — `recorded` is what says so."""
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][3]))

        assert response.data['totals'] == {
            'recorded': 0, 'present': 0, 'absent': 0, 'attendance_rate': 0.0,
        }
        assert response.data['by_subject'] == []

    def test_one_absence_and_no_other_rows_is_not_a_full_term_of_absence(
        self, cohort, authenticated_client,
    ):
        """s2 missed one lesson out of one registered, not one out of seven."""
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][2]))

        assert response.data['totals']['recorded'] == 1
        assert response.data['totals']['absent'] == 1

    def test_by_subject_splits_the_rate(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        assert response.data['by_subject'] == [
            {
                'offering_id': cohort['maths'].id, 'subject': 'Mathematics',
                'recorded': 3, 'present': 3, 'absent': 0,
                'attendance_rate': pytest.approx(100.0),
            },
            {
                'offering_id': cohort['physics'].id, 'subject': 'Physics',
                'recorded': 1, 'present': 0, 'absent': 1,
                'attendance_rate': pytest.approx(0.0),
            },
        ]

    def test_by_weekday_always_has_seven_entries(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        weekdays = response.data['by_weekday']
        assert [block['weekday'] for block in weekdays] == [0, 1, 2, 3, 4, 5, 6]
        assert weekdays[0]['recorded'] == 2      # two Mondays, both present
        assert weekdays[0]['attendance_rate'] == pytest.approx(100.0)
        assert weekdays[1]['attendance_rate'] == pytest.approx(0.0)   # Tuesday
        assert weekdays[4]['recorded'] == 0      # nothing on a Friday

    def test_by_month_groups_the_dates(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        assert response.data['by_month'] == [
            {
                'month': '2025-09', 'recorded': 4, 'present': 3, 'absent': 1,
                'attendance_rate': pytest.approx(75.0),
            },
        ]

    def test_class_comparison_is_aggregate_only(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][0].user)
        response = client.get(summary_url(cohort['students'][0]))

        comparison = response.data['class_comparison']
        assert comparison['class_size'] == 4
        # Pooled over all nine rows, not the mean of the four student rates.
        assert comparison['class_attendance_rate'] == pytest.approx(55.56)
        assert comparison['class_mean_rate'] == pytest.approx(31.25)
        assert comparison['rank'] == 1
        assert comparison['percentile'] == 88

        body = str(response.data)
        for student in cohort['students'][1:]:
            assert student.user.last_name not in body

    def test_include_class_stats_false_drops_the_comparison(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['students'][0].user)
        response = client.get(
            summary_url(cohort['students'][0]), {'include_class_stats': 'false'},
        )

        assert response.data['class_comparison'] is None

    def test_offering_filter_narrows_to_one_subject(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            summary_url(cohort['students'][0]),
            {'offering': cohort['physics'].id},
        )

        assert response.data['totals']['recorded'] == 1
        assert [b['subject'] for b in response.data['by_subject']] == ['Physics']

    def test_quarter_filters_on_the_schedules_own_quarter(
        self, cohort, authenticated_client,
    ):
        second_quarter = SubjectScheduleFactory(offering=cohort['maths'], quarter=2)
        session = ScheduleSessionFactory(
            schedule=second_quarter, weekday=3,
            time_start=time(12, 0), time_end=time(12, 45),
        )
        ScheduleAttendanceFactory(
            session=session, student=cohort['students'][0],
            date='2025-11-05', status='absent',
        )

        client = authenticated_client(AdminUserFactory())

        everything = client.get(summary_url(cohort['students'][0]))
        assert everything.data['totals']['recorded'] == 5

        first = client.get(summary_url(cohort['students'][0]), {'quarter': 1})
        assert first.data['totals']['recorded'] == 4
        assert first.data['filters']['quarter'] == 1

        second = client.get(summary_url(cohort['students'][0]), {'quarter': 2})
        assert second.data['totals'] == {
            'recorded': 1, 'present': 0, 'absent': 1, 'attendance_rate': 0.0,
        }

    def test_date_range_narrows_the_rows(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            summary_url(cohort['students'][0]),
            {'date_from': '2025-09-02', 'date_to': '2025-09-03'},
        )

        assert response.data['totals']['recorded'] == 2

    def test_parent_may_read_their_own_child(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])

        client = authenticated_client(parent.user)
        assert client.get(summary_url(cohort['students'][0])).status_code == 200

    def test_teacher_of_the_student_may_read(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        assert client.get(summary_url(cohort['students'][0])).status_code == 200

    def test_other_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][1].user)
        assert client.get(summary_url(cohort['students'][0])).status_code == 403

    def test_bad_quarter_is_400(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        assert client.get(
            summary_url(cohort['students'][0]), {'quarter': '9'},
        ).status_code == 400

    def test_anonymous_is_401(self, cohort, api_client):
        assert api_client.get(summary_url(cohort['students'][0])).status_code == 401


# ── Offering heatmap ──

@pytest.mark.django_db
class TestOfferingAttendanceHeatmap:

    def test_columns_are_date_and_session_pairs_oldest_first(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['maths']))

        assert response.status_code == 200
        assert [slot['date'] for slot in response.data['slots']] == [
            '2025-09-01', '2025-09-03', '2025-09-08',
        ]
        assert [slot['weekday'] for slot in response.data['slots']] == [0, 2, 0]
        assert [slot['time_start'] for slot in response.data['slots']] == [
            '09:00:00', '11:00:00', '09:00:00',
        ]
        assert response.data['slots'][0]['time_end'] == '09:45:00'
        assert response.data['slots'][0]['key'] == (
            f"2025-09-01:{cohort['monday'].id}"
        )

    def test_unregistered_cells_are_null_not_absent(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['maths']))

        assert response.data['matrix'] == [
            ['present', 'present', 'present'],   # s0
            ['present', 'absent', 'absent'],     # s1
            ['absent', None, None],              # s2 — two blanks, not two absences
            [None, None, None],                  # s3 — never registered
        ]

    def test_row_summary_divides_by_what_was_registered(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['maths']))

        assert response.data['row_summary'][1]['attendance_rate'] == pytest.approx(33.33)
        # s2: one absence out of one row, not one out of three slots.
        assert response.data['row_summary'][2] == {
            'recorded': 1, 'present': 0, 'absent': 1, 'attendance_rate': 0.0,
        }
        assert response.data['row_summary'][3]['recorded'] == 0

    def test_column_summary_finds_the_bad_day(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['maths']))

        assert [
            block['attendance_rate'] for block in response.data['column_summary']
        ] == [pytest.approx(66.67), pytest.approx(50.0), pytest.approx(50.0)]

    def test_totals_span_the_matrix(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['maths']))

        assert response.data['totals'] == {
            'recorded': 7, 'present': 4, 'absent': 3,
            'attendance_rate': pytest.approx(57.14),
        }
        assert response.data['slot_count'] == 3
        assert response.data['truncated'] is False

    def test_date_range_narrows_the_columns(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(
            heatmap_url(cohort['maths']), {'date_to': '2025-09-03'},
        )

        assert response.data['slot_count'] == 2

    def test_homeroom_teacher_may_read(self, cohort, authenticated_client):
        homeroom = TeacherFactory()
        HomeroomTeacherAssignment.objects.create(
            teacher=homeroom,
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(homeroom.user)
        assert client.get(heatmap_url(cohort['maths'])).status_code == 200

    def test_admin_may_read(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        assert client.get(heatmap_url(cohort['maths'])).status_code == 200

    def test_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][0].user)
        assert client.get(heatmap_url(cohort['maths'])).status_code == 403

    def test_parent_is_403(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])

        client = authenticated_client(parent.user)
        assert client.get(heatmap_url(cohort['maths'])).status_code == 403

    def test_unrelated_teacher_is_403(self, cohort, authenticated_client):
        client = authenticated_client(TeacherFactory().user)
        assert client.get(heatmap_url(cohort['maths'])).status_code == 403


# ── Class group overview ──

@pytest.mark.django_db
class TestClassGroupAttendanceOverview:

    def test_students_are_ranked_best_first(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(overview_url(cohort['class_group']))

        assert response.status_code == 200
        rows = response.data['students']
        assert [row['student']['id'] for row in rows] == [
            cohort['students'][0].id, cohort['students'][1].id,
            cohort['students'][2].id, cohort['students'][3].id,
        ]
        assert [row['attendance_rate'] for row in rows] == [
            pytest.approx(75.0), pytest.approx(50.0), 0.0, 0.0,
        ]
        # The two students on 0.0 share the better rank.
        assert [row['rank'] for row in rows] == [1, 2, 3, 3]

    def test_student_without_rows_still_appears(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(overview_url(cohort['class_group']))

        last = response.data['students'][3]
        assert last['student']['id'] == cohort['students'][3].id
        assert last['recorded'] == 0

    def test_at_risk_skips_students_with_nothing_recorded(
        self, cohort, authenticated_client,
    ):
        """No rows is no evidence — it is not a 0% attendance record."""
        client = authenticated_client(AdminUserFactory())
        response = client.get(overview_url(cohort['class_group']))

        at_risk_ids = [row['student']['id'] for row in response.data['at_risk']]
        assert at_risk_ids == [
            cohort['students'][0].id,   # 75%, below the default 90
            cohort['students'][1].id,   # 50%
            cohort['students'][2].id,   # 0% but with a row behind it
        ]
        assert cohort['students'][3].id not in at_risk_ids

    def test_at_risk_below_moves_the_threshold(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            overview_url(cohort['class_group']), {'at_risk_below': '60'},
        )

        assert [row['student']['id'] for row in response.data['at_risk']] == [
            cohort['students'][1].id, cohort['students'][2].id,
        ]
        assert response.data['filters']['at_risk_below'] == pytest.approx(60.0)

    def test_totals_pool_every_row_of_the_class(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(overview_url(cohort['class_group']))

        totals = response.data['totals']
        assert totals['recorded'] == 9
        assert totals['present'] == 5
        assert totals['absent'] == 4
        assert totals['attendance_rate'] == pytest.approx(55.56)
        assert totals['class_size'] == 4
        # Mean of the four per-student rates, which is a different number.
        assert totals['mean_student_rate'] == pytest.approx(31.25)

    def test_by_subject_covers_every_subject_taught_to_the_class(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(AdminUserFactory())
        response = client.get(overview_url(cohort['class_group']))

        assert [block['subject'] for block in response.data['by_subject']] == [
            'Mathematics', 'Physics',
        ]
        assert response.data['by_subject'][0]['recorded'] == 7
        assert response.data['by_subject'][1]['recorded'] == 2

    def test_quarter_filter_applies(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(overview_url(cohort['class_group']), {'quarter': 2})

        assert response.data['totals']['recorded'] == 0
        assert response.data['students'][0]['recorded'] == 0

    def test_homeroom_teacher_may_read(self, cohort, authenticated_client):
        homeroom = TeacherFactory()
        HomeroomTeacherAssignment.objects.create(
            teacher=homeroom,
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(homeroom.user)
        assert client.get(overview_url(cohort['class_group'])).status_code == 200

    def test_teacher_of_one_subject_may_read_the_whole_class(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        assert client.get(overview_url(cohort['class_group'])).status_code == 200

    def test_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][0].user)
        assert client.get(overview_url(cohort['class_group'])).status_code == 403

    def test_parent_is_403(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])

        client = authenticated_client(parent.user)
        assert client.get(overview_url(cohort['class_group'])).status_code == 403

    def test_unrelated_teacher_is_403(self, cohort, authenticated_client):
        client = authenticated_client(TeacherFactory().user)
        assert client.get(overview_url(cohort['class_group'])).status_code == 403

    def test_query_count_does_not_grow_with_class_size(
        self, cohort, authenticated_client, django_assert_max_num_queries,
    ):
        for index in range(4, 20):
            student = StudentFactory(academic_year=cohort['academic_year'])
            student.user.last_name = f'Number{index}'
            student.user.save()
            EnrollmentFactory(
                student=student,
                class_group=cohort['class_group'],
                academic_year=cohort['academic_year'],
            )
            ScheduleAttendanceFactory(
                session=cohort['monday'], student=student,
                date='2025-09-01', status='present',
            )

        client = authenticated_client(AdminUserFactory())
        with django_assert_max_num_queries(20):
            response = client.get(overview_url(cohort['class_group']))

        assert response.status_code == 200
        assert len(response.data['students']) == 20
