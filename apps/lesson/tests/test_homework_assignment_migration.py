"""
Spec 0005 AC-4 and AC-12 — the migrations keep every assignment's category and
mirror the homework that predates the sync hooks.

Runs the real migrations backwards and forwards, so it needs a transactional
database: the schema changes cannot happen inside the per-test transaction.
"""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core.factories import (
    EnrollmentFactory, HomeworkFactory, HomeworkGradeFactory, StudentFactory,
    SubjectAssignmentFactory, SubjectGradeFactory, TeachingAssignmentFactory,
)

BEFORE = [
    ('home', '0040_composite_school_fks'),
    ('lesson', '0028_scheduleattendance_one_per_slot'),
]
AFTER = [
    ('home', '0043_assignment_category_fk'),
    ('lesson', '0029_homework_subject_assignment_backfill'),
]


@pytest.fixture
def migrate_to(transactional_db):
    """Migrate to a set of nodes and hand back that state's apps; restore on teardown."""
    executor = MigrationExecutor(connection)

    def _migrate(targets):
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    yield _migrate

    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_ac4_ac12_migration_keeps_categories_and_mirrors_homework(migrate_to):
    teaching = TeachingAssignmentFactory()
    offering = teaching.offering
    student = StudentFactory()
    EnrollmentFactory(student=student, class_group=offering.class_group)

    exam = SubjectAssignmentFactory(offering=offering, category='exam', title='Exam')
    SubjectAssignmentFactory(offering=offering, category='final', title='Final')
    SubjectGradeFactory(assignment=exam, student=student, grade=40)
    homework = HomeworkFactory(
        teaching_assignment=teaching, description='Chapter 2', max_grade=15,
        due_date=datetime.date(2026, 9, 20), is_active=False,
    )
    HomeworkGradeFactory(homework=homework, student=student, grade=12, comments='good')

    # Back to before 0005: the category is a plain code again and the homework
    # mirror (made by the hooks just now) is gone, as it was in production.
    old_apps = migrate_to(BEFORE)
    OldAssignment = old_apps.get_model('home', 'SubjectAssignment')
    assert dict(OldAssignment.objects.values_list('title', 'category')) == {
        'Exam': 'exam', 'Final': 'final',
    }

    new_apps = migrate_to(AFTER)
    Assignment = new_apps.get_model('home', 'SubjectAssignment')
    SubjectGrade = new_apps.get_model('home', 'SubjectGrade')

    # AC-4: same codes, now as rows.
    assert dict(
        Assignment.objects.exclude(category__code='homework')
        .values_list('title', 'category__code')
    ) == {'Exam': 'exam', 'Final': 'final'}
    assert SubjectGrade.objects.get(assignment__title='Exam').grade == 40

    # AC-12: the homework is mirrored, fields and grade included.
    mirror = Assignment.objects.get(category__code='homework', detail_id=homework.pk)
    assert mirror.offering_id == offering.pk
    assert mirror.title == 'Chapter 2'
    assert mirror.max_grade == 15
    assert mirror.date == datetime.date(2026, 9, 20)
    assert mirror.is_active is False
    grade = SubjectGrade.objects.get(assignment=mirror, student_id=student.pk)
    assert (grade.grade, grade.comments) == (12, 'good')
