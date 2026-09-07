"""
Tests for the three read-only subject-grade analytics endpoints.

The recurring theme is the opposite of the topic-grade one: an unmarked
SubjectGrade is *not* a zero. Most of these assert an exact number that only
comes out right if the unmarked work was left out of the divisor rather than
folded in — and the `missing=zero` variants assert the number you get when it
is folded in on purpose.
"""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory, EnrollmentFactory,
    ParentFactory, StudentFactory, SubjectAssignmentFactory, SubjectFactory,
    SubjectGradeFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory,
)


def trajectory_url(student, offering):
    return reverse(
        'lesson-api:analytics-assignment-trajectory',
        args=[student.id, offering.id],
    )


def heatmap_url(offering):
    return reverse('lesson-api:analytics-assignment-heatmap', args=[offering.id])


def summary_url(student):
    return reverse('lesson-api:analytics-assignment-summary', args=[student.id])


def assignment_offerings_url():
    return reverse('lesson-api:analytics-assignment-offering-list')


@pytest.fixture
def cohort(db):
    """
    One offering, three enrolled students, three assignments of unequal size.

    The maxima differ on purpose — 20, 50 and 10 points — so that any test
    reading a percent proves the normalisation rather than the raw mark.

      s0  fully marked: 20/20, 25/50, 10/10  ->  100, 50, 100
      s1  half marked:  10/20, a null-grade placeholder, no row at all
      s2  nothing at all
    """
    academic_year = AcademicYearFactory(
        is_active=True,
        q1_start='2025-09-01', q1_end='2025-10-31',
        q2_start='2025-11-01', q2_end='2025-12-31',
    )
    class_group = ClassGroupFactory(academic_year=academic_year)
    offering = SubjectOfferingFactory(
        subject=SubjectFactory(name='Mathematics'),
        class_group=class_group,
        academic_year=academic_year,
    )

    students = []
    for index in range(3):
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

    quiz = SubjectAssignmentFactory(
        offering=offering, title='Quiz 1', category='lesson',
        max_grade=20, date='2025-09-01',
    )
    exam = SubjectAssignmentFactory(
        offering=offering, title='Exam 1', category='exam',
        max_grade=50, date='2025-09-10',
    )
    homework = SubjectAssignmentFactory(
        offering=offering, title='Homework 1', category='lesson',
        max_grade=10, date='2025-09-20',
    )

    s0_quiz = SubjectGradeFactory(
        assignment=quiz, student=students[0], grade=20, comments='Excellent',
    )
    s0_exam = SubjectGradeFactory(
        assignment=exam, student=students[0], grade=25, comments='Steady',
    )
    s0_homework = SubjectGradeFactory(
        assignment=homework, student=students[0], grade=10,
    )

    s1_quiz = SubjectGradeFactory(
        assignment=quiz, student=students[1], grade=10,
    )
    # A row with no mark: opened, not graded. Must not read as a zero.
    s1_exam = SubjectGradeFactory(
        assignment=exam, student=students[1], grade=None,
        comments='Needs submission',
    )

    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=offering)

    return {
        'academic_year': academic_year,
        'class_group': class_group,
        'offering': offering,
        'students': students,
        'assignments': [quiz, exam, homework],
        'grades': {
            's0_quiz': s0_quiz,
            's0_exam': s0_exam,
            's0_homework': s0_homework,
            's1_quiz': s1_quiz,
            's1_exam': s1_exam,
        },
        'teacher': teacher,
    }


# ── Trajectory ──

@pytest.mark.django_db
class TestAssignmentTrajectory:

    def test_percent_is_normalised_by_each_assignment_max_grade(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['students'][0].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        assert response.status_code == 200
        points = response.data['points']
        # 20/20, 25/50, 10/10 — three different maxima, one scale.
        assert [point['percent'] for point in points] == [100.0, 50.0, 100.0]
        assert [point['grade'] for point in points] == [20, 25, 10]
        assert [point['max_grade'] for point in points] == [20, 50, 10]

    def test_unmarked_work_is_left_out_of_the_mean(
        self, cohort, authenticated_client,
    ):
        """s1 has one mark of 50%, one null placeholder and one missing row."""
        client = authenticated_client(AdminUserFactory())
        response = client.get(trajectory_url(cohort['students'][1], cohort['offering']))

        summary = response.data['summary']
        assert summary['assignment_count'] == 3
        assert summary['graded_count'] == 1
        # 50 / 1, not 50 / 3.
        assert summary['student_mean'] == pytest.approx(50.0)
        assert response.data['grading']['missing_grades_as'] == 'excluded'

    def test_missing_zero_counts_unmarked_as_zero(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            trajectory_url(cohort['students'][1], cohort['offering']),
            {'missing': 'zero'},
        )

        summary = response.data['summary']
        # (50 + 0 + 0) / 3
        assert summary['student_mean'] == pytest.approx(16.67)
        assert response.data['grading']['missing_grades_as'] == 'zero'
        assert response.data['filters']['missing'] == 'zero'

    def test_graded_flag_separates_a_zero_from_an_unmarked_cell(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(AdminUserFactory())
        response = client.get(trajectory_url(cohort['students'][1], cohort['offering']))

        points = response.data['points']
        assert [point['graded'] for point in points] == [True, False, False]
        # Both unmarked points read 0.0 — only `graded` tells them apart.
        assert [point['percent'] for point in points] == [50.0, 0.0, 0.0]
        assert [point['grade'] for point in points] == [10, None, None]

    def test_class_band_excludes_unmarked_classmates(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        quiz, exam, homework = response.data['points']
        # Quiz: 100 and 50 entered, one student missing entirely -> mean of two.
        assert quiz['class_mean'] == pytest.approx(75.0)
        assert quiz['graded_class_count'] == 2
        assert quiz['class_size'] == 3
        # Exam: only s0 is marked; the null placeholder does not pull it down.
        assert exam['class_mean'] == pytest.approx(50.0)
        assert exam['graded_class_count'] == 1
        assert homework['class_mean'] == pytest.approx(100.0)

    def test_class_band_names_nobody(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][0].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        body = str(response.data)
        for student in cohort['students'][1:]:
            assert student.user.last_name not in body

    def test_rank_is_zero_for_an_unmarked_point(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(trajectory_url(cohort['students'][1], cohort['offering']))

        quiz, exam, _homework = response.data['points']
        assert quiz['rank'] == 2          # behind s0's 100
        assert exam['rank'] == 0          # no mark, so no place in the ranking

    def test_include_class_stats_false_drops_the_band(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['students'][0].user)
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'include_class_stats': 'false'},
        )

        assert 'class_mean' not in response.data['points'][0]
        assert response.data['summary']['class_mean'] is None
        assert response.data['summary']['delta'] is None

    def test_summary_splits_by_category(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        by_category = response.data['summary']['by_category']
        assert by_category['lesson']['assignment_count'] == 2
        assert by_category['lesson']['value'] == pytest.approx(100.0)
        assert by_category['exam']['assignment_count'] == 1
        assert by_category['exam']['value'] == pytest.approx(50.0)
        # No finals were set: an empty category reads 0.0 with a count of 0.
        assert by_category['final'] == {
            'assignment_count': 0, 'graded_count': 0, 'value': 0.0,
        }

    def test_category_filter_narrows_the_points(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'category': 'exam'},
        )

        assert [point['title'] for point in response.data['points']] == ['Exam 1']
        assert response.data['filters']['category'] == 'exam'

    def test_date_range_narrows_the_points(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'date_from': '2025-09-05', 'date_to': '2025-09-15'},
        )

        assert [point['title'] for point in response.data['points']] == ['Exam 1']

    def test_coverage_counts_entered_marks(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(trajectory_url(cohort['students'][1], cohort['offering']))

        assert response.data['summary']['coverage'] == {
            'possible_count': 3, 'graded_count': 1, 'graded_share': pytest.approx(33.33),
        }

    def test_parent_may_read_their_own_child(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])

        client = authenticated_client(parent.user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        assert response.status_code == 200

    def test_other_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][1].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        assert response.status_code == 403

    def test_offering_the_student_is_not_enrolled_in_is_404(
        self, cohort, authenticated_client,
    ):
        other = SubjectOfferingFactory(
            subject=SubjectFactory(name='Physics'),
            class_group=ClassGroupFactory(academic_year=cohort['academic_year']),
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(AdminUserFactory())
        response = client.get(trajectory_url(cohort['students'][0], other))

        assert response.status_code == 404

    def test_unknown_missing_value_is_400(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'missing': 'maybe'},
        )

        assert response.status_code == 400

    def test_anonymous_is_401(self, cohort, api_client):
        response = api_client.get(
            trajectory_url(cohort['students'][0], cohort['offering'])
        )
        assert response.status_code == 401


# ── Heatmap ──

@pytest.mark.django_db
class TestAssignmentAnalyticsOfferings:

    def test_mixed_admin_teacher_gets_own_taught_and_homeroom_offerings(
        self, cohort, authenticated_client,
    ):
        teacher = cohort['teacher']
        admin_group, _ = Group.objects.get_or_create(name='Admin')
        teacher.user.groups.add(admin_group)

        homeroom_subject = SubjectFactory(name='Chinese')
        homeroom_offering = SubjectOfferingFactory(
            subject=homeroom_subject,
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )
        unrelated = SubjectOfferingFactory(
            subject=SubjectFactory(name='Physics'),
            academic_year=cohort['academic_year'],
        )
        HomeroomTeacherAssignment.objects.create(
            teacher=teacher,
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(teacher.user)
        response = client.get(assignment_offerings_url())

        assert response.status_code == 200
        rows = {row['id']: row for row in response.data['offerings']}
        assert set(rows) == {cohort['offering'].id, homeroom_offering.id}
        assert rows[cohort['offering'].id]['access'] == 'teaching_and_homeroom'
        assert rows[cohort['offering'].id]['can_heatmap'] is True
        assert rows[homeroom_offering.id]['access'] == 'homeroom'
        assert rows[homeroom_offering.id]['can_heatmap'] is False
        assert unrelated.id not in rows

    def test_admin_can_request_a_specific_teacher(
        self, cohort, authenticated_client,
    ):
        admin = AdminUserFactory()

        client = authenticated_client(admin)
        response = client.get(
            assignment_offerings_url(), {'teacher': cohort['teacher'].id},
        )

        assert response.status_code == 200
        assert [row['id'] for row in response.data['offerings']] == [
            cohort['offering'].id,
        ]

    def test_teacher_cannot_request_another_teacher(
        self, cohort, authenticated_client,
    ):
        other = TeacherFactory()

        client = authenticated_client(other.user)
        response = client.get(
            assignment_offerings_url(), {'teacher': cohort['teacher'].id},
        )

        assert response.status_code == 403


@pytest.mark.django_db
class TestAssignmentHeatmap:

    def test_matrix_is_students_by_assignments(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']))

        assert response.status_code == 200
        assert len(response.data['students']) == 3
        assert [a['title'] for a in response.data['assignments']] == [
            'Quiz 1', 'Exam 1', 'Homework 1',
        ]
        assert response.data['matrix'] == [
            [100.0, 50.0, 100.0],   # s0
            [50.0, 0.0, 0.0],       # s1 — the last two are unmarked, not zero
            [0.0, 0.0, 0.0],        # s2 — nothing entered at all
        ]
        assert response.data['graded'] == [
            [True, True, True],
            [True, False, False],
            [False, False, False],
        ]

    def test_raw_grades_keep_the_original_marks(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']))

        assert response.data['raw_grades'][0] == [20, 25, 10]
        assert response.data['raw_grades'][1] == [10, None, None]

    def test_edit_metadata_is_aligned_with_cells(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']))

        grades = cohort['grades']
        assert response.data['grade_ids'] == [
            [grades['s0_quiz'].id, grades['s0_exam'].id, grades['s0_homework'].id],
            [grades['s1_quiz'].id, grades['s1_exam'].id, None],
            [None, None, None],
        ]
        assert response.data['comments'] == [
            ['Excellent', 'Steady', ''],
            ['', 'Needs submission', ''],
            ['', '', ''],
        ]

    def test_means_exclude_unmarked_cells(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']))

        # Quiz: 100 and 50 -> 75. Exam: only 50 entered. Homework: only 100.
        assert response.data['column_means'] == [
            pytest.approx(75.0), pytest.approx(50.0), pytest.approx(100.0),
        ]
        # s1's row is one mark of 50, not 50/3.
        assert response.data['row_means'][1] == pytest.approx(50.0)
        assert response.data['row_means'][2] == pytest.approx(0.0)

    def test_missing_zero_pulls_the_means_down(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']), {'missing': 'zero'})

        assert response.data['column_means'] == [
            pytest.approx(50.0), pytest.approx(16.67), pytest.approx(33.33),
        ]

    def test_coverage_spans_the_whole_block(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']))

        assert response.data['coverage']['possible_count'] == 9
        assert response.data['coverage']['graded_count'] == 4

    def test_homeroom_teacher_who_does_not_teach_is_403(
        self, cohort, authenticated_client,
    ):
        homeroom = TeacherFactory()
        HomeroomTeacherAssignment.objects.create(
            teacher=homeroom,
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(homeroom.user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_admin_is_403(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][0].user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_parent_is_403(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])

        client = authenticated_client(parent.user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_unrelated_teacher_is_403(self, cohort, authenticated_client):
        client = authenticated_client(TeacherFactory().user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403


# ── Per-subject summary ──

@pytest.mark.django_db
class TestAssignmentSummary:

    def test_one_axis_per_subject_ordered_by_name(
        self, cohort, authenticated_client,
    ):
        SubjectOfferingFactory(
            subject=SubjectFactory(name='Art'),
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        assert response.status_code == 200
        assert [axis['subject'] for axis in response.data['axes']] == [
            'Art', 'Mathematics',
        ]

    def test_subject_with_no_assignments_still_gets_an_axis(
        self, cohort, authenticated_client,
    ):
        SubjectOfferingFactory(
            subject=SubjectFactory(name='Art'),
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )

        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        art = response.data['axes'][0]
        assert art['assignment_count'] == 0
        assert art['value'] == 0.0
        # ...and it is kept out of the averages, so it cannot be "weakest".
        assert response.data['summary']['axis_count'] == 2
        assert response.data['summary']['subject_count'] == 1
        assert response.data['summary']['weakest']['subject'] == 'Mathematics'

    def test_axis_carries_the_category_split(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        axis = response.data['axes'][0]
        assert axis['value'] == pytest.approx(83.33)
        assert axis['by_category']['lesson']['value'] == pytest.approx(100.0)
        assert axis['by_category']['exam']['value'] == pytest.approx(50.0)

    def test_class_mean_and_percentile(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(cohort['students'][0]))

        axis = response.data['axes'][0]
        # Per-student means: s0 83.33, s1 50.0, s2 0.0 -> 44.44.
        assert axis['class_mean'] == pytest.approx(44.44)
        assert axis['percentile'] == 83

    def test_include_class_mean_false_drops_them(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            summary_url(cohort['students'][0]), {'include_class_mean': 'false'},
        )

        assert 'class_mean' not in response.data['axes'][0]
        assert response.data['summary']['class_overall_mean'] is None

    def test_quarter_filters_by_the_years_own_dates(
        self, cohort, authenticated_client,
    ):
        """Q1 covers all three assignments; Q2 covers none of them."""
        client = authenticated_client(AdminUserFactory())

        first = client.get(summary_url(cohort['students'][0]), {'quarter': 1})
        assert first.data['axes'][0]['assignment_count'] == 3
        assert first.data['filters']['date_from'] == '2025-09-01'
        assert first.data['filters']['date_to'] == '2025-10-31'

        second = client.get(summary_url(cohort['students'][0]), {'quarter': 2})
        assert second.data['axes'][0]['assignment_count'] == 0

    def test_quarter_without_dates_is_400(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        # The fixture year has no q3 dates, so the filter cannot be honoured.
        response = client.get(summary_url(cohort['students'][0]), {'quarter': 3})

        assert response.status_code == 400
        assert 'quarter' in response.data

    def test_student_without_enrollment_gets_empty_axes(
        self, cohort, authenticated_client,
    ):
        stranger = StudentFactory(academic_year=cohort['academic_year'])

        client = authenticated_client(AdminUserFactory())
        response = client.get(summary_url(stranger))

        assert response.status_code == 200
        assert response.data['axes'] == []
        assert response.data['summary']['overall_mean'] == 0.0

    def test_other_student_is_403(self, cohort, authenticated_client):
        client = authenticated_client(cohort['students'][1].user)
        assert client.get(summary_url(cohort['students'][0])).status_code == 403

    def test_query_count_does_not_grow_with_subject_count(
        self, cohort, authenticated_client, django_assert_max_num_queries,
    ):
        for name in ('Art', 'Biology', 'Chemistry', 'Drama'):
            offering = SubjectOfferingFactory(
                subject=SubjectFactory(name=name),
                class_group=cohort['class_group'],
                academic_year=cohort['academic_year'],
            )
            assignment = SubjectAssignmentFactory(
                offering=offering, max_grade=100, date='2025-09-15',
            )
            for student in cohort['students']:
                SubjectGradeFactory(
                    assignment=assignment, student=student, grade=70,
                )

        client = authenticated_client(AdminUserFactory())
        with django_assert_max_num_queries(20):
            response = client.get(summary_url(cohort['students'][0]))

        assert response.status_code == 200
        assert len(response.data['axes']) == 5
