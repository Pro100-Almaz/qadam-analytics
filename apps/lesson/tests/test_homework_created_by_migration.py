"""
Spec 0017 AC-17 — the migration fills `created_by` and `quarter` from the
teaching assignment they replace.

Runs the real migrations backwards and forwards, so it needs a transactional
database: the schema changes cannot happen inside the per-test transaction.
"""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core.factories import HomeworkFactory, TeachingAssignmentFactory

BEFORE = [('lesson', '0031_historicalhomeworkgrade')]
AFTER = [('lesson', '0034_remove_homework_teaching_assignment')]


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


def test_ac17_migration_backfills_created_by_and_quarter(migrate_to):
    in_q2 = TeachingAssignmentFactory(quarter=2)
    in_q3 = TeachingAssignmentFactory(quarter=3)
    due = datetime.date(2026, 11, 5)
    mirrored = HomeworkFactory(teaching_assignment=in_q2, due_date=due)
    unquartered = HomeworkFactory(teaching_assignment=in_q3, due_date=due)
    orphaned = HomeworkFactory(teaching_assignment=in_q2, due_date=due)

    old = migrate_to(BEFORE)
    Homework = old.get_model('lesson', 'Homework')
    SubjectAssignment = old.get_model('home', 'SubjectAssignment')
    # The reverse step re-linked every row to its author's assignment.
    assert Homework.objects.get(pk=mirrored.pk).teaching_assignment_id == in_q2.pk
    # The shapes the backfill has to cope with: a mirror whose quarter was
    # never resolved, and a homework whose assignment had been purged.
    SubjectAssignment.objects.filter(
        category__code='homework', detail_id=unquartered.pk,
    ).update(quarter=None)
    Homework.objects.filter(pk=orphaned.pk).update(teaching_assignment=None)

    new = migrate_to(AFTER)
    Homework = new.get_model('lesson', 'Homework')
    SubjectAssignment = new.get_model('home', 'SubjectAssignment')

    def state(homework):
        row = Homework.objects.get(pk=homework.pk)
        mirror = SubjectAssignment.objects.get(
            category__code='homework', detail_id=homework.pk,
        )
        return row.created_by_id, row.quarter, mirror.quarter

    assert state(mirrored) == (in_q2.teacher_id, 2, 2)
    assert state(unquartered) == (in_q3.teacher_id, 3, 3)
    assert state(orphaned) == (None, 2, 2)
