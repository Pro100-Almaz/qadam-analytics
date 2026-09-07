import pytest
from decimal import Decimal

from apps.lesson.models import Lesson, Topic, TopicGrade
from core.factories import (
    StudentFactory, AcademicYearFactory, ClassGroupFactory,
    SubjectOfferingFactory, EnrollmentFactory, LessonFactory,
    TopicFactory, TopicGradeFactory, SubtopicFactory,
)


@pytest.mark.django_db
class TestLessonGradeCalculation:

    @pytest.fixture
    def grading_setup(self):
        academic_year = AcademicYearFactory(is_active=True)
        class_group = ClassGroupFactory(academic_year=academic_year)
        offering = SubjectOfferingFactory(
            class_group=class_group,
            academic_year=academic_year,
        )
        lesson = LessonFactory(offering=offering, quarter=1)

        t1 = TopicFactory(lesson=lesson, title='Homework', weight=40, order=0)
        t2 = TopicFactory(lesson=lesson, title='Classwork', weight=30, order=1)
        t3 = TopicFactory(lesson=lesson, title='Exam', weight=30, order=2)

        students = []
        for i in range(3):
            s = StudentFactory(academic_year=academic_year)
            EnrollmentFactory(
                student=s,
                class_group=class_group,
                academic_year=academic_year,
            )
            students.append(s)

        return {
            'offering': offering,
            'lesson': lesson,
            'topics': [t1, t2, t3],
            'students': students,
        }

    def test_perfect_scores_equal_max_grade(self, grading_setup):
        lesson = grading_setup['lesson']
        student = grading_setup['students'][0]
        for topic in grading_setup['topics']:
            TopicGradeFactory(topic=topic, student=student, grade=100)

        result = lesson.calculate_student_grade(student)
        # (100*40 + 100*30 + 100*30) / 100 = 100
        assert result == pytest.approx(100.0)

    def test_zero_scores_equal_zero(self, grading_setup):
        lesson = grading_setup['lesson']
        student = grading_setup['students'][0]
        for topic in grading_setup['topics']:
            TopicGradeFactory(topic=topic, student=student, grade=0)

        result = lesson.calculate_student_grade(student)
        assert result == pytest.approx(0.0)

    def test_weighted_average_is_correct(self, grading_setup):
        """
        Topics weighted [40, 30, 30]. Student scores [100, 50, 80] out of 100.
        Expected: (100*40/100) + (50*30/100) + (80*30/100) = 40 + 15 + 24 = 79
        """
        lesson = grading_setup['lesson']
        student = grading_setup['students'][0]
        topics = grading_setup['topics']
        scores = [100, 50, 80]
        for topic, score in zip(topics, scores):
            TopicGradeFactory(topic=topic, student=student, grade=score)

        result = lesson.calculate_student_grade(student)
        assert result == pytest.approx(79.0)

    def test_missing_grades_treated_as_zero(self, grading_setup):
        """Student has grades for 2 of 3 topics. Missing = 0."""
        lesson = grading_setup['lesson']
        student = grading_setup['students'][0]
        topics = grading_setup['topics']
        TopicGradeFactory(topic=topics[0], student=student, grade=100)
        TopicGradeFactory(topic=topics[1], student=student, grade=100)
        # topics[2] has no grade -> 0

        result = lesson.calculate_student_grade(student)
        # (100*40 + 100*30 + 0*30) / 100 = 70
        assert result == pytest.approx(70.0)


@pytest.mark.django_db
class TestBulkGradeCalculation:

    @pytest.fixture
    def bulk_setup(self):
        academic_year = AcademicYearFactory(is_active=True)
        class_group = ClassGroupFactory(academic_year=academic_year)
        offering = SubjectOfferingFactory(
            class_group=class_group,
            academic_year=academic_year,
        )

        lessons = [
            LessonFactory(offering=offering, quarter=1, title=f'L{i}')
            for i in range(3)
        ]

        for lesson in lessons:
            TopicFactory(lesson=lesson, title='Main', weight=100, order=0)

        students = []
        for i in range(5):
            s = StudentFactory(academic_year=academic_year)
            EnrollmentFactory(
                student=s,
                class_group=class_group,
                academic_year=academic_year,
            )
            students.append(s)

        return {
            'offering': offering,
            'lessons': lessons,
            'students': students,
        }

    def test_bulk_calculation_matches_individual(self, bulk_setup):
        lessons = bulk_setup['lessons']
        students = bulk_setup['students']

        for lesson in lessons:
            topic = lesson.topics.first()
            for i, student in enumerate(students):
                TopicGradeFactory(
                    topic=topic,
                    student=student,
                    grade=(i + 1) * 20,
                )

        bulk_results = Lesson.calculate_grades_bulk(lessons, students)

        for lesson in lessons:
            for student in students:
                individual = lesson.calculate_student_grade(student)
                bulk = bulk_results[(lesson.id, student.id)]
                assert individual == pytest.approx(bulk), (
                    f"Mismatch for lesson {lesson.id}, student {student.id}: "
                    f"individual={individual}, bulk={bulk}"
                )

    def test_bulk_with_no_grades_returns_zeros(self, bulk_setup):
        lessons = bulk_setup['lessons']
        students = bulk_setup['students']
        results = Lesson.calculate_grades_bulk(lessons, students)
        for key, grade in results.items():
            assert grade == pytest.approx(0.0)


@pytest.mark.django_db
class TestSubtopicGradeRollup:

    def test_subtopic_grades_roll_up_to_parent(self):
        academic_year = AcademicYearFactory(is_active=True)
        offering = SubjectOfferingFactory(
            class_group=ClassGroupFactory(academic_year=academic_year),
            academic_year=academic_year,
        )
        lesson = LessonFactory(offering=offering)
        parent_topic = TopicFactory(lesson=lesson, title='Parent', weight=100)
        sub1 = TopicFactory(
            lesson=lesson, parent=parent_topic, title='Sub A', weight=60, order=0,
        )
        sub2 = TopicFactory(
            lesson=lesson, parent=parent_topic, title='Sub B', weight=40, order=1,
        )

        student = StudentFactory(academic_year=academic_year)
        TopicGradeFactory(topic=sub1, student=student, grade=80)
        TopicGradeFactory(topic=sub2, student=student, grade=60)

        # (80*60 + 60*40) / (60+40) = (4800+2400)/100 = 72
        result = parent_topic.calculate_subtopics_grade(student)
        assert result == pytest.approx(72.0)

    def test_subtopic_no_grades_returns_zero(self):
        academic_year = AcademicYearFactory(is_active=True)
        offering = SubjectOfferingFactory(
            class_group=ClassGroupFactory(academic_year=academic_year),
            academic_year=academic_year,
        )
        lesson = LessonFactory(offering=offering)
        parent_topic = TopicFactory(lesson=lesson, title='Parent', weight=100)
        TopicFactory(lesson=lesson, parent=parent_topic, title='Sub A', weight=50)
        TopicFactory(lesson=lesson, parent=parent_topic, title='Sub B', weight=50)

        student = StudentFactory(academic_year=academic_year)
        result = parent_topic.calculate_subtopics_grade(student)
        assert result == pytest.approx(0.0)


@pytest.mark.django_db
class TestQueryEfficiency:

    @pytest.mark.slow
    def test_bulk_grade_bounded_queries(self, django_assert_num_queries):
        academic_year = AcademicYearFactory(is_active=True)
        class_group = ClassGroupFactory(academic_year=academic_year)
        offering = SubjectOfferingFactory(
            class_group=class_group,
            academic_year=academic_year,
        )
        lessons = [LessonFactory(offering=offering, title=f'L{i}') for i in range(5)]
        for lesson in lessons:
            TopicFactory(lesson=lesson, title='T1', weight=50)
            TopicFactory(lesson=lesson, title='T2', weight=50)

        students = []
        for i in range(10):
            s = StudentFactory(academic_year=academic_year)
            students.append(s)
            for lesson in lessons:
                for topic in lesson.topics.all():
                    TopicGradeFactory(topic=topic, student=s, grade=75)

        # Bulk calc should use bounded queries (not O(students * lessons))
        with django_assert_num_queries(2):
            Lesson.calculate_grades_bulk(lessons, students)
