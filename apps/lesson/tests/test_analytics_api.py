"""
Tests for the three read-only analytics endpoints.

The recurring theme is the zero-fill rule: a missing TopicGrade counts as 0
everywhere, so most of these assert an exact number that only comes out right
if the ungraded topics were folded in at zero rather than skipped.
"""

import pytest
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment
from apps.lesson.api.analytics import (
    _percentile, _percentile_rank, _rank, _trend_slope,
    lesson_grade_matrix, topic_grade_matrix,
)
from apps.lesson.models import QuarterGradeSnapshot
from core.factories import (
    AcademicYearFactory, AdminUserFactory, ClassGroupFactory, EnrollmentFactory,
    LessonFactory, ParentFactory, StudentFactory, SubjectFactory,
    SubjectOfferingFactory, TeacherFactory, TeachingAssignmentFactory,
    TopicFactory, TopicGradeFactory,
)


def trajectory_url(student, offering):
    return reverse(
        'lesson-api:analytics-student-trajectory',
        args=[student.id, offering.id],
    )


def heatmap_url(offering):
    return reverse('lesson-api:analytics-topic-heatmap', args=[offering.id])


def radar_url(student):
    return reverse('lesson-api:analytics-subject-radar', args=[student.id])


@pytest.fixture
def cohort(db):
    """
    One offering, three enrolled students, two lessons of three weighted topics.

    Grades are laid out so the zero-fill rule is visible:
      lesson 1 — s0 fully graded, s1 partially graded, s2 not graded at all
      lesson 2 — s0 and s1 graded, s2 not graded
    """
    academic_year = AcademicYearFactory(is_active=True)
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

    lessons = []
    topics = []
    for index in range(2):
        lesson = LessonFactory(
            offering=offering,
            title=f'Lesson {index + 1}',
            quarter=1,
            unit=1,
            order=index,
            date=f'2025-09-0{index + 1}',
        )
        lesson_topics = [
            TopicFactory(lesson=lesson, title='Homework', weight=50, order=0),
            TopicFactory(lesson=lesson, title='Classwork', weight=30, order=1),
            TopicFactory(lesson=lesson, title='Quiz', weight=20, order=2),
        ]
        lessons.append(lesson)
        topics.append(lesson_topics)

    # Lesson 1: s0 = 100/100/100 -> 100. s1 = 80 on Homework only -> 40.
    for topic in topics[0]:
        TopicGradeFactory(topic=topic, student=students[0], grade=100)
    TopicGradeFactory(topic=topics[0][0], student=students[1], grade=80)

    # Lesson 2: s0 = 60/60/60 -> 60. s1 = 100 on Homework + Classwork -> 80.
    for topic in topics[1]:
        TopicGradeFactory(topic=topic, student=students[0], grade=60)
    TopicGradeFactory(topic=topics[1][0], student=students[1], grade=100)
    TopicGradeFactory(topic=topics[1][1], student=students[1], grade=100)

    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=offering)

    return {
        'academic_year': academic_year,
        'class_group': class_group,
        'offering': offering,
        'students': students,
        'lessons': lessons,
        'topics': topics,
        'teacher': teacher,
    }


# ── Pure helpers ──

@pytest.mark.django_db
class TestAggregationHelpers:

    def test_lesson_grade_matrix_zero_fills_missing_topics(self, cohort):
        grades, coverage = lesson_grade_matrix(cohort['lessons'], cohort['students'])
        lesson1, lesson2 = cohort['lessons']
        s0, s1, s2 = cohort['students']

        # 100*0.5 + 100*0.3 + 100*0.2
        assert grades[(lesson1.id, s0.id)] == pytest.approx(100.0)
        # 80*0.5 only; the two ungraded topics contribute 0
        assert grades[(lesson1.id, s1.id)] == pytest.approx(40.0)
        # nothing entered at all
        assert grades[(lesson1.id, s2.id)] == pytest.approx(0.0)
        # 100*0.5 + 100*0.3
        assert grades[(lesson2.id, s1.id)] == pytest.approx(80.0)

    def test_lesson_grade_matrix_reports_coverage(self, cohort):
        _, coverage = lesson_grade_matrix(cohort['lessons'], cohort['students'])
        lesson1 = cohort['lessons'][0]
        s0, s1, s2 = cohort['students']

        assert coverage[(lesson1.id, s0.id)] == (3, 3)
        assert coverage[(lesson1.id, s1.id)] == (1, 3)
        assert coverage[(lesson1.id, s2.id)] == (0, 3)

    def test_lesson_grade_matrix_matches_model_calculation(self, cohort):
        """The helper must not drift from Lesson.calculate_student_grade."""
        grades, _ = lesson_grade_matrix(cohort['lessons'], cohort['students'])
        for lesson in cohort['lessons']:
            for student in cohort['students']:
                assert grades[(lesson.id, student.id)] == pytest.approx(
                    lesson.calculate_student_grade(student)
                )

    def test_lesson_grade_matrix_is_bounded_in_queries(
        self, cohort, django_assert_num_queries,
    ):
        with django_assert_num_queries(2):
            lesson_grade_matrix(cohort['lessons'], cohort['students'])

    def test_lesson_grade_matrix_handles_empty_inputs(self, cohort):
        assert lesson_grade_matrix([], cohort['students']) == ({}, {})
        assert lesson_grade_matrix(cohort['lessons'], []) == ({}, {})

    def test_topic_matrix_folds_same_titles_across_lessons(self, cohort):
        columns, cells, truncated = topic_grade_matrix(
            cohort['lessons'], cohort['students'],
        )
        assert not truncated
        assert [column['key'] for column in columns] == [
            'Homework', 'Classwork', 'Quiz',
        ]
        # Two lessons folded into each column.
        assert all(column['lesson_count'] == 2 for column in columns)
        assert all(column['topic_count'] == 2 for column in columns)

    def test_topic_matrix_divides_by_full_column_size(self, cohort):
        """
        s1 scored 80 and 100 on Homework -> 90. On Quiz they have one entered
        grade out of two topic rows, so the divisor stays 2, not 1.
        """
        _, cells, _ = topic_grade_matrix(cohort['lessons'], cohort['students'])
        s0, s1, s2 = cohort['students']

        assert cells[('Homework', s1.id)] == (pytest.approx(90.0), 2)
        # Classwork: 0 in lesson 1, 100 in lesson 2 -> 50 over two rows
        assert cells[('Classwork', s1.id)] == (pytest.approx(50.0), 1)
        # Quiz: never graded
        assert cells[('Quiz', s1.id)] == (pytest.approx(0.0), 0)
        # s0 graded everywhere: (100 + 60) / 2
        assert cells[('Homework', s0.id)] == (pytest.approx(80.0), 2)
        assert cells[('Quiz', s2.id)] == (pytest.approx(0.0), 0)

    def test_topic_matrix_group_by_topic_keeps_one_column_per_row(self, cohort):
        columns, _, _ = topic_grade_matrix(
            cohort['lessons'], cohort['students'], group_by='topic',
        )
        assert len(columns) == 6
        assert all(column['topic_count'] == 1 for column in columns)

    def test_topic_matrix_namespaces_subtopics_under_parent(self, cohort):
        parent = cohort['topics'][0][0]
        TopicFactory(
            lesson=cohort['lessons'][0], parent=parent, title='Part A',
            weight=100, order=0,
        )
        columns, _, _ = topic_grade_matrix(
            cohort['lessons'], cohort['students'], include_subtopics=True,
        )
        assert 'Homework › Part A' in [column['key'] for column in columns]

    def test_percentile_interpolates(self):
        assert _percentile([0.0, 50.0, 100.0], 0.5) == pytest.approx(50.0)
        assert _percentile([0.0, 100.0], 0.25) == pytest.approx(25.0)
        assert _percentile([], 0.5) == 0.0
        assert _percentile([42.0], 0.75) == pytest.approx(42.0)

    def test_rank_is_one_based_and_ties_share_best(self):
        assert _rank([100.0, 40.0, 0.0], 100.0) == 1
        assert _rank([100.0, 40.0, 0.0], 40.0) == 2
        assert _rank([50.0, 50.0, 0.0], 50.0) == 1

    def test_percentile_rank_counts_ties_as_half(self):
        """An all-zero class must not read as the 0th percentile."""
        assert _percentile_rank([0.0, 0.0, 0.0], 0.0) == 50
        assert _percentile_rank([0.0, 50.0, 100.0], 100.0) == 83

    def test_trend_slope_signs(self):
        assert _trend_slope([10.0, 20.0, 30.0]) == pytest.approx(10.0)
        assert _trend_slope([30.0, 20.0, 10.0]) == pytest.approx(-10.0)
        assert _trend_slope([50.0]) == 0.0
        assert _trend_slope([]) == 0.0


# ── Trajectory ──

@pytest.mark.django_db
class TestStudentTrajectory:

    def test_returns_point_per_lesson_in_order(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        assert response.status_code == 200
        body = response.json()
        assert [point['title'] for point in body['points']] == ['Lesson 1', 'Lesson 2']
        assert [point['student_grade'] for point in body['points']] == [100.0, 60.0]
        assert body['grading'] == {'missing_topics_as': 'zero'}

    def test_ungraded_student_reads_zero_with_zero_coverage(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(trajectory_url(cohort['students'][2], cohort['offering']))

        body = response.json()
        assert [point['student_grade'] for point in body['points']] == [0.0, 0.0]
        assert all(
            point['coverage'] == {'topic_count': 3, 'graded_topic_count': 0}
            for point in body['points']
        )
        assert body['summary']['student_mean'] == 0.0

    def test_partial_coverage_is_reported_alongside_the_grade(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(trajectory_url(cohort['students'][1], cohort['offering']))

        points = response.json()['points']
        assert points[0]['student_grade'] == 40.0
        assert points[0]['coverage'] == {'topic_count': 3, 'graded_topic_count': 1}
        assert points[1]['student_grade'] == 80.0
        assert points[1]['coverage'] == {'topic_count': 3, 'graded_topic_count': 2}

    def test_class_band_includes_ungraded_students(self, cohort, authenticated_client):
        """
        Lesson 1 grades are 100 / 40 / 0. The band must reflect all three —
        dropping the ungraded student would put the mean at 70, not 46.67.
        """
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        first = response.json()['points'][0]
        assert first['class_size'] == 3
        assert first['class_mean'] == pytest.approx(46.67, abs=0.01)
        assert first['class_median'] == pytest.approx(40.0)
        assert first['class_min'] == 0.0
        assert first['class_max'] == 100.0
        assert first['rank'] == 1

    def test_summary_reports_delta_and_trend(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(trajectory_url(cohort['students'][0], cohort['offering']))

        summary = response.json()['summary']
        assert summary['lesson_count'] == 2
        assert summary['student_mean'] == pytest.approx(80.0)
        # class means: 46.67 and 46.67 -> delta 33.33
        assert summary['delta'] == pytest.approx(33.33, abs=0.01)
        assert summary['trend_slope'] < 0  # 100 then 60
        assert summary['coverage'] == {'topic_count': 6, 'graded_topic_count': 6}

    def test_include_class_stats_false_omits_the_band(
        self, cohort, authenticated_client,
    ):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'include_class_stats': 'false'},
        )

        body = response.json()
        assert 'class_mean' not in body['points'][0]
        assert body['points'][0]['student_grade'] == 100.0
        assert body['summary']['class_mean'] is None
        assert body['summary']['delta'] is None

    def test_quarter_filter_narrows_lessons(self, cohort, authenticated_client):
        LessonFactory(
            offering=cohort['offering'], title='Q2 lesson', quarter=2,
            date='2025-11-01', order=0,
        )
        client = authenticated_client(cohort['teacher'].user)

        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'quarter': 2},
        )
        body = response.json()
        assert [point['title'] for point in body['points']] == ['Q2 lesson']
        assert body['filters']['quarter'] == 2

    def test_date_range_filter(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']),
            {'date_from': '2025-09-02'},
        )
        assert [p['title'] for p in response.json()['points']] == ['Lesson 2']

    def test_student_sees_own_trajectory(self, cohort, authenticated_client):
        student = cohort['students'][0]
        client = authenticated_client(student.user)
        response = client.get(trajectory_url(student, cohort['offering']))
        assert response.status_code == 200

    def test_parent_sees_their_child(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])
        client = authenticated_client(parent.user)
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering'])
        )
        assert response.status_code == 200

    def test_unrelated_student_is_forbidden(self, cohort, authenticated_client):
        outsider = StudentFactory(academic_year=cohort['academic_year'])
        client = authenticated_client(outsider.user)
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering'])
        )
        assert response.status_code == 403

    def test_offering_the_student_is_not_enrolled_in_is_404(
        self, cohort, authenticated_client,
    ):
        other_class = ClassGroupFactory(
            academic_year=cohort['academic_year'], letter='B',
        )
        other_offering = SubjectOfferingFactory(
            class_group=other_class, academic_year=cohort['academic_year'],
        )
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            trajectory_url(cohort['students'][0], other_offering)
        )
        assert response.status_code == 404

    def test_requires_authentication(self, cohort, api_client):
        response = api_client.get(
            trajectory_url(cohort['students'][0], cohort['offering'])
        )
        assert response.status_code in (401, 403)

    @pytest.mark.parametrize('params', [
        {'quarter': 9},
        {'quarter': 'x'},
        {'unit': 0},
        {'date_from': 'not-a-date'},
    ])
    def test_invalid_filters_are_400(self, cohort, authenticated_client, params):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(
            trajectory_url(cohort['students'][0], cohort['offering']), params,
        )
        assert response.status_code == 400


# ── Heatmap ──

@pytest.mark.django_db
class TestTopicHeatmap:

    def test_matrix_is_students_by_topics(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(heatmap_url(cohort['offering']))

        assert response.status_code == 200
        body = response.json()
        assert len(body['students']) == 3
        assert [topic['key'] for topic in body['topics']] == [
            'Homework', 'Classwork', 'Quiz',
        ]
        assert len(body['matrix']) == 3
        assert all(len(row) == 3 for row in body['matrix'])
        assert body['class_size'] == 3
        assert body['truncated'] is False

    def test_cells_are_dense_and_zero_filled(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        body = client.get(heatmap_url(cohort['offering'])).json()

        names = [student['id'] for student in body['students']]
        row_of = {student_id: index for index, student_id in enumerate(names)}
        s0, s1, s2 = cohort['students']

        # s0 graded everywhere: (100 + 60) / 2 on each topic
        assert body['matrix'][row_of[s0.id]] == [80.0, 80.0, 80.0]
        # s1: Homework (80+100)/2, Classwork (0+100)/2, Quiz never graded
        assert body['matrix'][row_of[s1.id]] == [90.0, 50.0, 0.0]
        # s2: nothing at all
        assert body['matrix'][row_of[s2.id]] == [0.0, 0.0, 0.0]
        assert all(value is not None for row in body['matrix'] for value in row)

    def test_coverage_matrix_tracks_entered_grades(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        body = client.get(heatmap_url(cohort['offering'])).json()

        row_of = {
            student['id']: index
            for index, student in enumerate(body['students'])
        }
        s1, s2 = cohort['students'][1], cohort['students'][2]

        # s1 has 2 Homework grades, 1 Classwork, 0 Quiz
        assert body['coverage'][row_of[s1.id]] == [2, 1, 0]
        assert body['coverage'][row_of[s2.id]] == [0, 0, 0]

    def test_row_and_column_means(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        body = client.get(heatmap_url(cohort['offering'])).json()

        row_of = {
            student['id']: index
            for index, student in enumerate(body['students'])
        }
        assert body['row_means'][row_of[cohort['students'][0].id]] == pytest.approx(80.0)
        # Homework column: 80, 90, 0
        assert body['column_means'][0] == pytest.approx(56.67, abs=0.01)

    def test_group_by_topic_expands_columns(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        body = client.get(
            heatmap_url(cohort['offering']), {'group_by': 'topic'},
        ).json()

        assert len(body['topics']) == 6
        assert body['filters']['group_by'] == 'topic'
        assert all(len(row) == 6 for row in body['matrix'])

    def test_include_subtopics_adds_namespaced_columns(
        self, cohort, authenticated_client,
    ):
        TopicFactory(
            lesson=cohort['lessons'][0], parent=cohort['topics'][0][0],
            title='Part A', weight=100, order=0,
        )
        client = authenticated_client(cohort['teacher'].user)
        body = client.get(
            heatmap_url(cohort['offering']), {'include_subtopics': 'true'},
        ).json()

        assert 'Homework › Part A' in [topic['key'] for topic in body['topics']]

    def test_homeroom_teacher_of_the_class_may_read(
        self, cohort, authenticated_client,
    ):
        homeroom = TeacherFactory()
        HomeroomTeacherAssignment.objects.create(
            teacher=homeroom,
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )
        client = authenticated_client(homeroom.user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 200

    def test_admin_may_read(self, cohort, authenticated_client):
        client = authenticated_client(AdminUserFactory())
        assert client.get(heatmap_url(cohort['offering'])).status_code == 200

    def test_unrelated_teacher_is_forbidden(self, cohort, authenticated_client):
        client = authenticated_client(TeacherFactory().user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_student_is_forbidden(self, cohort, authenticated_client):
        """The payload is every classmate's scores — students use trajectory."""
        client = authenticated_client(cohort['students'][0].user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_parent_is_forbidden(self, cohort, authenticated_client):
        parent = ParentFactory()
        parent.students.add(cohort['students'][0])
        client = authenticated_client(parent.user)
        assert client.get(heatmap_url(cohort['offering'])).status_code == 403

    def test_offering_without_lessons_returns_empty_columns(
        self, cohort, authenticated_client,
    ):
        empty = SubjectOfferingFactory(
            class_group=cohort['class_group'],
            academic_year=cohort['academic_year'],
        )
        TeachingAssignmentFactory(teacher=cohort['teacher'], offering=empty)
        client = authenticated_client(cohort['teacher'].user)
        body = client.get(heatmap_url(empty)).json()

        assert body['topics'] == []
        assert body['matrix'] == [[], [], []]
        assert body['lesson_count'] == 0

    def test_invalid_group_by_is_400(self, cohort, authenticated_client):
        client = authenticated_client(cohort['teacher'].user)
        response = client.get(
            heatmap_url(cohort['offering']), {'group_by': 'nonsense'},
        )
        assert response.status_code == 400


# ── Radar ──

@pytest.fixture
def radar_cohort(cohort):
    """The base cohort plus a second subject taught to the same class."""
    physics = SubjectOfferingFactory(
        subject=SubjectFactory(name='Physics', language_group='rus'),
        class_group=cohort['class_group'],
        academic_year=cohort['academic_year'],
    )
    lesson = LessonFactory(
        offering=physics, title='Physics 1', quarter=1, order=0,
        date='2025-09-03',
    )
    topic = TopicFactory(lesson=lesson, title='Test', weight=100, order=0)
    TopicGradeFactory(topic=topic, student=cohort['students'][0], grade=50)
    TopicGradeFactory(topic=topic, student=cohort['students'][1], grade=90)
    # students[2] ungraded -> 0

    cohort['physics'] = physics
    return cohort


@pytest.mark.django_db
class TestSubjectRadar:

    def test_axis_per_subject_ordered_by_name(
        self, radar_cohort, authenticated_client,
    ):
        client = authenticated_client(radar_cohort['teacher'].user)
        response = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        )

        assert response.status_code == 200
        body = response.json()
        assert [axis['subject'] for axis in body['axes']] == [
            'Mathematics', 'Physics',
        ]
        assert body['quarter'] == 1

    def test_live_values_match_snapshot_methodology(
        self, radar_cohort, authenticated_client,
    ):
        """
        Maths lesson grades for s0 are 100 and 60, so the quarter mean is 80 —
        the mean of zero-filled lesson grades, exactly as freeze_quarter_grades
        computes it.
        """
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        ).json()

        maths = body['axes'][0]
        assert maths['value'] == pytest.approx(80.0)
        assert maths['source'] == 'live'
        assert maths['lesson_count'] == 2
        assert maths['graded_lesson_count'] == 2

    def test_ungraded_student_reads_zero_across_axes(
        self, radar_cohort, authenticated_client,
    ):
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][2]), {'quarter': 1},
        ).json()

        assert [axis['value'] for axis in body['axes']] == [0.0, 0.0]
        assert all(axis['graded_lesson_count'] == 0 for axis in body['axes'])
        # Both subjects ran lessons, so both count — the student genuinely
        # scored zero rather than having nothing scheduled.
        assert body['summary']['subject_count'] == 2
        assert body['summary']['overall_mean'] == 0.0

    def test_class_mean_and_percentile(self, radar_cohort, authenticated_client):
        """Maths quarter means are 80 / 60 / 0, so the class mean is 46.67."""
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        ).json()

        maths = body['axes'][0]
        assert maths['class_mean'] == pytest.approx(46.67, abs=0.01)
        assert maths['percentile'] == 83

    def test_include_class_mean_false_omits_comparison(
        self, radar_cohort, authenticated_client,
    ):
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]),
            {'quarter': 1, 'include_class_mean': 'false'},
        ).json()

        assert 'class_mean' not in body['axes'][0]
        assert 'percentile' not in body['axes'][0]
        assert body['summary']['class_overall_mean'] is None

    def test_summary_names_strongest_and_weakest(
        self, radar_cohort, authenticated_client,
    ):
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        ).json()

        summary = body['summary']
        assert summary['strongest'] == {'subject': 'Mathematics', 'value': 80.0}
        assert summary['weakest'] == {'subject': 'Physics', 'value': 50.0}
        assert summary['axis_count'] == 2
        assert summary['subject_count'] == 2
        assert summary['sources'] == {'snapshot': 0, 'live': 2}

    def test_snapshot_is_preferred_when_present(
        self, radar_cohort, authenticated_client,
    ):
        admin = AdminUserFactory()
        for student, percentage in zip(radar_cohort['students'], [95, 40, 10]):
            QuarterGradeSnapshot.objects.create(
                student=student,
                offering=radar_cohort['offering'],
                quarter=1,
                academic_year=radar_cohort['academic_year'],
                final_grade=percentage,
                percentage=percentage,
                letter_grade='A',
                lesson_count=2,
                graded_lesson_count=2,
                frozen_by=admin,
            )

        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        ).json()

        maths = body['axes'][0]
        assert maths['source'] == 'snapshot'
        assert maths['value'] == pytest.approx(95.0)
        assert maths['letter_grade'] == 'A'
        # class mean now comes from the frozen rows: (95 + 40 + 10) / 3
        assert maths['class_mean'] == pytest.approx(48.33, abs=0.01)
        # Physics has no snapshot, so it stays live on the same radar
        assert body['axes'][1]['source'] == 'live'
        assert body['summary']['sources'] == {'snapshot': 1, 'live': 1}

    def test_source_live_ignores_snapshots(
        self, radar_cohort, authenticated_client,
    ):
        admin = AdminUserFactory()
        QuarterGradeSnapshot.objects.create(
            student=radar_cohort['students'][0],
            offering=radar_cohort['offering'],
            quarter=1,
            academic_year=radar_cohort['academic_year'],
            final_grade=95, percentage=95, letter_grade='A',
            lesson_count=2, graded_lesson_count=2, frozen_by=admin,
        )
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]),
            {'quarter': 1, 'source': 'live'},
        ).json()

        assert body['axes'][0]['source'] == 'live'
        assert body['axes'][0]['value'] == pytest.approx(80.0)

    def test_source_snapshot_omits_unfrozen_axes(
        self, radar_cohort, authenticated_client,
    ):
        admin = AdminUserFactory()
        QuarterGradeSnapshot.objects.create(
            student=radar_cohort['students'][0],
            offering=radar_cohort['offering'],
            quarter=1,
            academic_year=radar_cohort['academic_year'],
            final_grade=95, percentage=95, letter_grade='A',
            lesson_count=2, graded_lesson_count=2, frozen_by=admin,
        )
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]),
            {'quarter': 1, 'source': 'snapshot'},
        ).json()

        assert [axis['subject'] for axis in body['axes']] == ['Mathematics']

    def test_subject_without_lessons_keeps_its_axis(
        self, radar_cohort, authenticated_client,
    ):
        """Vertex count must stay stable — read lesson_count, not value."""
        SubjectOfferingFactory(
            subject=SubjectFactory(name='Zoology'),
            class_group=radar_cohort['class_group'],
            academic_year=radar_cohort['academic_year'],
        )
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        ).json()

        zoology = next(a for a in body['axes'] if a['subject'] == 'Zoology')
        assert zoology['value'] == 0.0
        assert zoology['lesson_count'] == 0

    def test_lessonless_subject_is_excluded_from_the_summary(
        self, radar_cohort, authenticated_client,
    ):
        """
        A subject that ran no lessons is drawn — vertex counts must stay
        stable — but it is not the student's weakest subject, and it must not
        drag the overall mean down. Maths 80 and Physics 50 average to 65
        whether or not Zoology exists.
        """
        SubjectOfferingFactory(
            subject=SubjectFactory(name='Zoology'),
            class_group=radar_cohort['class_group'],
            academic_year=radar_cohort['academic_year'],
        )
        client = authenticated_client(radar_cohort['teacher'].user)
        body = client.get(
            radar_url(radar_cohort['students'][0]), {'quarter': 1},
        ).json()

        summary = body['summary']
        assert summary['axis_count'] == 3       # Zoology is drawn
        assert summary['subject_count'] == 2    # but not counted
        assert summary['overall_mean'] == pytest.approx(65.0)
        assert summary['weakest'] == {'subject': 'Physics', 'value': 50.0}

    def test_summary_is_empty_when_no_subject_has_lessons(
        self, cohort, authenticated_client,
    ):
        empty_year = AcademicYearFactory(year='2030/2031', is_active=False)
        empty_class = ClassGroupFactory(academic_year=empty_year, letter='C')
        student = StudentFactory(academic_year=empty_year)
        EnrollmentFactory(
            student=student, class_group=empty_class, academic_year=empty_year,
        )
        SubjectOfferingFactory(
            subject=SubjectFactory(name='Astronomy'),
            class_group=empty_class, academic_year=empty_year,
        )

        client = authenticated_client(AdminUserFactory())
        body = client.get(
            radar_url(student),
            {'academic_year': empty_year.id, 'quarter': 1},
        ).json()

        summary = body['summary']
        assert summary['axis_count'] == 1
        assert summary['subject_count'] == 0
        assert summary['overall_mean'] == 0.0
        assert summary['strongest'] is None
        assert summary['weakest'] is None
        assert summary['class_overall_mean'] is None

    def test_query_count_does_not_grow_with_subject_count(
        self, radar_cohort, authenticated_client, django_assert_max_num_queries,
    ):
        for index in range(6):
            offering = SubjectOfferingFactory(
                subject=SubjectFactory(name=f'Extra {index}'),
                class_group=radar_cohort['class_group'],
                academic_year=radar_cohort['academic_year'],
            )
            lesson = LessonFactory(offering=offering, quarter=1, order=0)
            TopicFactory(lesson=lesson, title='T', weight=100, order=0)

        client = authenticated_client(AdminUserFactory())
        with django_assert_max_num_queries(15):
            response = client.get(
                radar_url(radar_cohort['students'][0]), {'quarter': 1},
            )
        assert response.status_code == 200
        assert len(response.json()['axes']) == 8

    def test_student_without_enrollment_gets_empty_axes(
        self, radar_cohort, authenticated_client,
    ):
        loner = StudentFactory(academic_year=radar_cohort['academic_year'])
        client = authenticated_client(AdminUserFactory())
        body = client.get(radar_url(loner), {'quarter': 1}).json()

        assert body['axes'] == []
        assert body['summary']['subject_count'] == 0

    def test_unrelated_student_is_forbidden(
        self, radar_cohort, authenticated_client,
    ):
        outsider = StudentFactory(academic_year=radar_cohort['academic_year'])
        client = authenticated_client(outsider.user)
        response = client.get(radar_url(radar_cohort['students'][0]))
        assert response.status_code == 403

    def test_invalid_source_is_400(self, radar_cohort, authenticated_client):
        client = authenticated_client(radar_cohort['teacher'].user)
        response = client.get(
            radar_url(radar_cohort['students'][0]), {'source': 'guess'},
        )
        assert response.status_code == 400
