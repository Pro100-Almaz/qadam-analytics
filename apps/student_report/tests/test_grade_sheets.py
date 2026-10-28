import io
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework import status

from apps.home.models import (
    HomeroomTeacherAssignment,
    QuarterGrade,
    SubjectAssignment,
    SubjectGrade,
)
from core.factories import (
    AdminUserFactory,
    AssignmentCategoryFactory,
    ClassGroupFactory,
    EnrollmentFactory,
    ParentFactory,
    StudentFactory,
    SubjectFactory,
    SubjectOfferingFactory,
    TeacherFactory,
    TeachingAssignmentFactory,
)

XLSX_CONTENT_TYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)


def open_workbook(response):
    return load_workbook(io.BytesIO(response.content))


@pytest.fixture
def year_with_quarters(academic_year):
    """The active year with Q1/Q2 date ranges, which assignments are filed by."""
    academic_year.q1_start = date(2025, 9, 1)
    academic_year.q1_end = date(2025, 10, 31)
    academic_year.q2_start = date(2025, 11, 1)
    academic_year.q2_end = date(2025, 12, 31)
    academic_year.save()
    return academic_year


@pytest.fixture
def sheet_setup(year_with_quarters):
    """
    One class group, two students, two subjects, graded work in Q1 and Q2.

    Math has two Q1 assignments (one grade carries a comment, one student is
    ungraded on the second); Art has one. A Q2 Math assignment exists so that
    quarter filtering has something to exclude.

    Quarter grades: Alice has Q1 Math 5 and Art 4; Bob has none in Q1, only a
    Q2 Math 3. Alice also has a Q1 grade of 2 on another class group's Math
    offering. The Q2 and other-class rows exist so that filtering has
    something to exclude.
    """
    class_group = ClassGroupFactory(academic_year=year_with_quarters)

    alice = StudentFactory(academic_year=year_with_quarters)
    alice.user.first_name, alice.user.last_name = 'Alice', 'Abbott'
    alice.user.save()
    bob = StudentFactory(academic_year=year_with_quarters)
    bob.user.first_name, bob.user.last_name = 'Bob', 'Barnes'
    bob.user.save()

    for student in (alice, bob):
        EnrollmentFactory(
            student=student,
            class_group=class_group,
        )

    math = SubjectFactory(name='Mathematics')
    art = SubjectFactory(name='Art')
    math_offering = SubjectOfferingFactory(
        subject=math, class_group=class_group,
    )
    art_offering = SubjectOfferingFactory(
        subject=art, class_group=class_group,
    )

    # Created out of date order on purpose — columns must come back sorted.
    quiz = SubjectAssignment.objects.create(
        offering=math_offering, title='Quiz 2', max_grade=10,
        date=date(2025, 10, 20), category=AssignmentCategoryFactory(code='lesson'),
    )
    entry_test = SubjectAssignment.objects.create(
        offering=math_offering, title='Entry test', max_grade=10,
        date=date(2025, 9, 10), category=AssignmentCategoryFactory(code='exam'),
    )
    q2_exam = SubjectAssignment.objects.create(
        offering=math_offering, title='Winter exam', max_grade=10,
        date=date(2025, 12, 1), category=AssignmentCategoryFactory(code='exam'),
    )
    still_life = SubjectAssignment.objects.create(
        offering=art_offering, title='Still life', max_grade=5,
        date=date(2025, 9, 25), category=AssignmentCategoryFactory(code='lesson'),
    )

    SubjectGrade.objects.create(
        assignment=entry_test, student=alice, grade=9, comments='Great start',
    )
    SubjectGrade.objects.create(assignment=entry_test, student=bob, grade=6)
    SubjectGrade.objects.create(assignment=quiz, student=alice, grade=8)
    SubjectGrade.objects.create(assignment=still_life, student=alice, grade=5)
    SubjectGrade.objects.create(assignment=q2_exam, student=alice, grade=4)

    QuarterGrade.objects.create(
        student=alice, offering=math_offering, quarter=1, grade=5,
    )
    QuarterGrade.objects.create(
        student=alice, offering=art_offering, quarter=1, grade=4,
    )
    QuarterGrade.objects.create(
        student=bob, offering=math_offering, quarter=2, grade=3,
    )
    other_class_math = SubjectOfferingFactory(
        subject=math,
        class_group=ClassGroupFactory(academic_year=year_with_quarters),
    )
    QuarterGrade.objects.create(
        student=alice, offering=other_class_math, quarter=1, grade=2,
    )

    homeroom_teacher = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(
        teacher=homeroom_teacher,
        class_group=class_group,
    )
    math_teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=math_teacher, offering=math_offering)

    return {
        'academic_year': year_with_quarters,
        'class_group': class_group,
        'alice': alice,
        'bob': bob,
        'math': math,
        'art': art,
        'math_offering': math_offering,
        'art_offering': art_offering,
        'entry_test': entry_test,
        'quiz': quiz,
        'q2_exam': q2_exam,
        'homeroom_teacher': homeroom_teacher,
        'math_teacher': math_teacher,
    }


def class_group_url(class_group):
    return reverse(
        'student-report-api:class-group-grade-sheet',
        kwargs={'class_group_id': class_group.pk},
    )


def student_url(student):
    return reverse(
        'student-report-api:student-grade-sheet',
        kwargs={'student_id': student.pk},
    )


@pytest.mark.django_db
class TestClassGroupGradeSheet:

    def test_homeroom_teacher_gets_a_sheet_per_subject(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Type'] == XLSX_CONTENT_TYPE

        wb = open_workbook(response)
        assert wb.sheetnames == ['Quarter Grades', 'Art', 'Mathematics']

    def test_columns_are_date_ordered_and_quarter_scoped(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )

        ws = open_workbook(response)['Mathematics']
        headers = [ws.cell(row=4, column=col).value for col in range(1, 5)]

        # Entry test (10.09) precedes Quiz 2 (20.10); the Q2 exam is absent,
        # so the Quarter Grade column follows Quiz 2 directly.
        assert headers[0] == 'Student'
        assert headers[1].startswith('Entry test')
        assert headers[2].startswith('Quiz 2')
        assert headers[3] == 'Quarter Grade'

    def test_cells_carry_grades_dashes_and_comments(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )

        ws = open_workbook(response)['Mathematics']
        # Row 5 is Abbott, row 6 is Barnes — ordered by last name.
        assert ws.cell(row=5, column=1).value == 'Alice Abbott'
        assert ws.cell(row=5, column=2).value == 9
        assert ws.cell(row=5, column=2).comment.text.endswith('Great start')
        assert ws.cell(row=6, column=1).value == 'Bob Barnes'
        assert ws.cell(row=6, column=2).value == 6
        assert ws.cell(row=6, column=3).value == '-'

    def test_subject_filter_leaves_one_sheet(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'subject': sheet_setup['math'].pk},
        )

        assert response.status_code == status.HTTP_200_OK
        assert open_workbook(response).sheetnames == ['Mathematics']

    def test_student_ordering_gives_a_sheet_per_student(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'ordering': 'student'},
        )

        wb = open_workbook(response)
        assert set(wb.sheetnames) == {
            'Quarter Grades', 'Alice Abbott', 'Bob Barnes',
        }

        ws = wb['Alice Abbott']
        labels = [
            ws.cell(row=row, column=1).value for row in range(4, 12)
        ]
        assert 'Art' in labels
        assert 'Mathematics' in labels

    def test_subject_teacher_needs_the_subject_parameter(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['math_teacher'].user)
        url = class_group_url(sheet_setup['class_group'])

        denied = client.get(url, {'quarter': 1})
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        allowed = client.get(url, {'quarter': 1, 'subject': sheet_setup['math'].pk})
        assert allowed.status_code == status.HTTP_200_OK

    def test_subject_teacher_cannot_reach_a_subject_they_do_not_teach(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['math_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'subject': sheet_setup['art'].pk},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_reads_any_class_group(self, authenticated_client, sheet_setup):
        client = authenticated_client(AdminUserFactory())
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_unrelated_student_is_denied(self, authenticated_client, sheet_setup):
        client = authenticated_client(sheet_setup['alice'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestStudentGradeSheet:

    def test_student_reads_their_own_sheet(self, authenticated_client, sheet_setup):
        client = authenticated_client(sheet_setup['alice'].user)
        response = client.get(
            student_url(sheet_setup['alice']),
            {'quarter': 1, 'ordering': 'student'},
        )

        assert response.status_code == status.HTTP_200_OK
        wb = open_workbook(response)
        assert wb.sheetnames == ['Quarter Grades', 'Alice Abbott']

    def test_sheet_holds_only_that_student(self, authenticated_client, sheet_setup):
        client = authenticated_client(sheet_setup['alice'].user)
        response = client.get(student_url(sheet_setup['alice']), {'quarter': 1})

        ws = open_workbook(response)['Mathematics']
        assert ws.cell(row=5, column=1).value == 'Alice Abbott'
        assert ws.cell(row=6, column=1).value is None

    def test_parent_reads_their_child(self, authenticated_client, sheet_setup):
        parent = ParentFactory()
        parent.students.add(sheet_setup['alice'])

        client = authenticated_client(parent.user)
        response = client.get(student_url(sheet_setup['alice']), {'quarter': 1})
        assert response.status_code == status.HTTP_200_OK

    def test_parent_of_another_child_is_denied(
        self, authenticated_client, sheet_setup,
    ):
        parent = ParentFactory()
        parent.students.add(sheet_setup['bob'])

        client = authenticated_client(parent.user)
        response = client.get(student_url(sheet_setup['alice']), {'quarter': 1})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_classmate_is_denied(self, authenticated_client, sheet_setup):
        client = authenticated_client(sheet_setup['bob'].user)
        response = client.get(student_url(sheet_setup['alice']), {'quarter': 1})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_homeroom_teacher_reads_the_student(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(student_url(sheet_setup['alice']), {'quarter': 1})
        assert response.status_code == status.HTTP_200_OK

    def test_subject_teacher_needs_the_subject_parameter(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['math_teacher'].user)
        url = student_url(sheet_setup['alice'])

        assert client.get(url, {'quarter': 1}).status_code == status.HTTP_403_FORBIDDEN
        allowed = client.get(url, {'quarter': 1, 'subject': sheet_setup['math'].pk})
        assert allowed.status_code == status.HTTP_200_OK

    def test_unenrolled_student_reports_the_missing_enrollment(
        self, authenticated_client, sheet_setup,
    ):
        loner = StudentFactory(academic_year=sheet_setup['academic_year'])
        client = authenticated_client(loner.user)
        response = client.get(student_url(loner), {'quarter': 1})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'student' in response.json()

    def test_outsider_gets_403_not_the_enrollment_detail(
        self, authenticated_client, sheet_setup,
    ):
        loner = StudentFactory(academic_year=sheet_setup['academic_year'])
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(student_url(loner), {'quarter': 1})

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGradeSheetParameters:

    def test_quarter_is_required(self, authenticated_client, sheet_setup):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(class_group_url(sheet_setup['class_group']))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'quarter' in response.json()

    @pytest.mark.parametrize('quarter', ['0', '5', 'two', ''])
    def test_quarter_is_validated(self, authenticated_client, sheet_setup, quarter):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': quarter},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_ordering_and_subject_are_mutually_exclusive(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {
                'quarter': 1,
                'subject': sheet_setup['math'].pk,
                'ordering': 'student',
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'ordering' in response.json()

    def test_unknown_ordering_is_rejected(self, authenticated_client, sheet_setup):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'ordering': 'teacher'},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_subject_not_taught_to_the_class_is_rejected(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(AdminUserFactory())
        other_subject = SubjectFactory(name='Astronomy')
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'subject': other_subject.pk},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'subject' in response.json()

    def test_unconfigured_quarter_dates_are_reported(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 3},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'quarter' in response.json()

    def test_filename_survives_non_ascii_names(
        self, authenticated_client, sheet_setup,
    ):
        student = sheet_setup['alice']
        student.user.first_name, student.user.last_name = 'Айгүл', 'Сериккызы'
        student.user.save()

        client = authenticated_client(student.user)
        response = client.get(student_url(student), {'quarter': 1})

        disposition = response['Content-Disposition']
        assert response.status_code == status.HTTP_200_OK
        assert "filename*=UTF-8''" in disposition
        assert disposition.startswith('attachment; filename="Grades_')


def quarter_grade_queries(captured):
    return [
        q for q in captured.captured_queries
        if QuarterGrade._meta.db_table in q['sql']
    ]


@pytest.mark.django_db
class TestQuarterGrades:
    """Spec 0013 — quarter grades in the grade sheets."""

    def test_ac1_subject_sheets_end_with_the_quarter_grade_column(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )
        wb = open_workbook(response)

        math = wb['Mathematics']
        assert math.cell(row=4, column=4).value == 'Quarter Grade'
        assert math.cell(row=5, column=4).value == 5  # Alice
        assert math.max_column == 4

        art = wb['Art']
        assert art.cell(row=4, column=3).value == 'Quarter Grade'
        assert art.cell(row=5, column=3).value == 4  # Alice

    def test_ac2_student_tables_end_with_the_quarter_grade_column(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'ordering': 'student'},
        )
        ws = open_workbook(response)['Alice Abbott']

        # Art table: header row 4, grades row 5. Math table: rows 7 and 8.
        assert ws.cell(row=4, column=3).value == 'Quarter Grade'
        assert ws.cell(row=5, column=1).value == 'Art'
        assert ws.cell(row=5, column=3).value == 4
        assert ws.cell(row=7, column=4).value == 'Quarter Grade'
        assert ws.cell(row=8, column=1).value == 'Mathematics'
        assert ws.cell(row=8, column=4).value == 5

    def test_ac3_missing_quarter_grade_is_an_empty_cell(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        url = class_group_url(sheet_setup['class_group'])

        by_subject = open_workbook(client.get(url, {'quarter': 1}))
        bob_row = by_subject['Mathematics'][6]
        assert bob_row[3].value is None

        by_student = open_workbook(
            client.get(url, {'quarter': 1, 'ordering': 'student'}),
        )
        assert by_student['Bob Barnes'].cell(row=8, column=4).value is None

    def test_ac4_other_quarters_and_offerings_never_appear(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        url = class_group_url(sheet_setup['class_group'])

        # Bob's Q2 Math grade stays out of Q1 ...
        q1 = open_workbook(client.get(url, {'quarter': 1}))
        assert q1['Mathematics'].cell(row=6, column=4).value is None
        # ... and is the only one in Q2, where Alice's Q1 grades are absent.
        q2 = open_workbook(client.get(url, {'quarter': 2}))
        math = q2['Mathematics']
        assert math.cell(row=4, column=3).value == 'Quarter Grade'
        assert math.cell(row=5, column=3).value is None
        assert math.cell(row=6, column=3).value == 3

        # Alice's grade of 2 belongs to another class group's offering.
        values = {
            cell.value
            for sheet in q1.worksheets
            for row in sheet.iter_rows(min_row=5)
            for cell in row
        }
        assert 2 not in values

    def test_ac5_subject_without_assignments_still_shows_quarter_grades(
        self, authenticated_client, sheet_setup,
    ):
        biology = SubjectOfferingFactory(
            subject=SubjectFactory(name='Biology'),
            class_group=sheet_setup['class_group'],
        )
        QuarterGrade.objects.create(
            student=sheet_setup['alice'], offering=biology, quarter=1, grade=3,
        )
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        url = class_group_url(sheet_setup['class_group'])

        ws = open_workbook(client.get(url, {'quarter': 1}))['Biology']
        assert ws.cell(row=4, column=2).value == 'Quarter Grade'
        assert ws.cell(row=5, column=1).value == 'Alice Abbott'
        assert ws.cell(row=5, column=2).value == 3
        assert ws.cell(row=6, column=1).value == 'Bob Barnes'
        assert ws.cell(row=6, column=2).value is None

        # Biology sorts after Art: its table is rows 7-8 of the student sheet.
        ws = open_workbook(
            client.get(url, {'quarter': 1, 'ordering': 'student'}),
        )['Alice Abbott']
        assert ws.cell(row=7, column=2).value == 'Quarter Grade'
        assert ws.cell(row=8, column=1).value == 'Biology'
        assert ws.cell(row=8, column=2).value == 3

    @pytest.mark.parametrize('ordering', ['subject', 'student'])
    def test_ac6_summary_sheet_comes_first_with_students_by_subjects(
        self, authenticated_client, sheet_setup, ordering,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']),
            {'quarter': 1, 'ordering': ordering},
        )
        wb = open_workbook(response)

        assert wb.sheetnames[0] == 'Quarter Grades'
        ws = wb['Quarter Grades']
        assert [ws.cell(row=4, column=c).value for c in range(1, 4)] == [
            'Student', 'Art', 'Mathematics',
        ]
        assert [ws.cell(row=5, column=c).value for c in range(1, 4)] == [
            'Alice Abbott', 4, 5,
        ]
        assert [ws.cell(row=6, column=c).value for c in range(1, 4)] == [
            'Bob Barnes', None, None,
        ]

    def test_ac6_student_endpoint_summary_holds_only_that_student(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            student_url(sheet_setup['alice']), {'quarter': 1},
        )
        wb = open_workbook(response)

        assert wb.sheetnames[0] == 'Quarter Grades'
        ws = wb['Quarter Grades']
        assert ws.cell(row=5, column=1).value == 'Alice Abbott'
        assert ws.cell(row=6, column=1).value is None

    @pytest.mark.parametrize('url_for', [
        lambda setup: class_group_url(setup['class_group']),
        lambda setup: student_url(setup['alice']),
    ])
    def test_ac7_subject_filter_has_no_summary_sheet(
        self, authenticated_client, sheet_setup, url_for,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            url_for(sheet_setup),
            {'quarter': 1, 'subject': sheet_setup['math'].pk},
        )

        wb = open_workbook(response)
        assert wb.sheetnames == ['Mathematics']
        assert wb['Mathematics'].cell(row=5, column=4).value == 5

    def test_ac8_summary_keeps_its_name_when_a_subject_shares_it(
        self, authenticated_client, sheet_setup,
    ):
        SubjectOfferingFactory(
            subject=SubjectFactory(name='Quarter Grades'),
            class_group=sheet_setup['class_group'],
        )
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        response = client.get(
            class_group_url(sheet_setup['class_group']), {'quarter': 1},
        )

        wb = open_workbook(response)
        assert wb.sheetnames[0] == 'Quarter Grades'
        assert wb['Quarter Grades'].cell(row=1, column=1).value.startswith(
            'Quarter Grades — ',
        )
        assert 'Quarter Grades (2)' in wb.sheetnames
        assert wb['Quarter Grades (2)'].cell(row=1, column=1).value.startswith(
            'Quarter Grades — ',
        )
        assert wb['Quarter Grades (2)'].cell(row=4, column=2).value == (
            'Quarter Grade'
        )

    @pytest.mark.parametrize('reader', ['student', 'parent'])
    def test_ac9_student_and_parent_see_quarter_grades(
        self, authenticated_client, sheet_setup, reader,
    ):
        alice = sheet_setup['alice']
        if reader == 'parent':
            parent = ParentFactory()
            parent.students.add(alice)
            user = parent.user
        else:
            user = alice.user

        client = authenticated_client(user)
        response = client.get(student_url(alice), {'quarter': 1})

        assert response.status_code == status.HTTP_200_OK
        wb = open_workbook(response)
        summary = wb['Quarter Grades']
        assert summary.cell(row=5, column=2).value == 4  # Art
        assert summary.cell(row=5, column=3).value == 5  # Mathematics
        assert wb['Mathematics'].cell(row=5, column=4).value == 5

    def test_ac10_quarter_grades_cost_one_query(
        self, authenticated_client, sheet_setup,
    ):
        client = authenticated_client(sheet_setup['homeroom_teacher'].user)
        url = class_group_url(sheet_setup['class_group'])

        with CaptureQueriesContext(connection) as small:
            assert client.get(url, {'quarter': 1}).status_code == 200

        for name in ('Chemistry', 'History', 'Music'):
            offering = SubjectOfferingFactory(
                subject=SubjectFactory(name=name),
                class_group=sheet_setup['class_group'],
            )
            for _ in range(3):
                student = StudentFactory(
                    academic_year=sheet_setup['academic_year'],
                )
                EnrollmentFactory(
                    student=student, class_group=sheet_setup['class_group'],
                )
                QuarterGrade.objects.create(
                    student=student, offering=offering, quarter=1, grade=4,
                )

        with CaptureQueriesContext(connection) as large:
            assert client.get(url, {'quarter': 1}).status_code == 200

        assert len(quarter_grade_queries(small)) == 1
        assert len(quarter_grade_queries(large)) == 1
