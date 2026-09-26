"""
Spec 0004 AC-6 — the migration that adds the one-row-per-slot constraint first
collapses any duplicates it would otherwise trip over, keeping the newest.

Runs the real migration backwards and forwards, so it needs a transactional
database: the schema changes cannot happen inside the per-test transaction.
"""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core.factories import ScheduleSessionFactory, StudentFactory

BEFORE = ('lesson', '0027_school_not_null')
AFTER = ('lesson', '0028_scheduleattendance_one_per_slot')
DAY = datetime.date(2026, 9, 24)


@pytest.fixture
def migrate_to(transactional_db):
    """Migrate to a node and hand back that state's apps; restore on teardown."""
    executor = MigrationExecutor(connection)

    def _migrate(target):
        executor.loader.build_graph()
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    yield _migrate

    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_ac6_migration_keeps_newest_row_per_slot(migrate_to, capsys):
    session = ScheduleSessionFactory()
    student = StudentFactory()
    other_session = ScheduleSessionFactory(
        schedule=session.schedule, weekday=1,
    )

    old_apps = migrate_to(BEFORE)
    Attendance = old_apps.get_model('lesson', 'ScheduleAttendance')

    def row(session_id, status, created_at):
        obj = Attendance.objects.create(
            session_id=session_id, student_id=student.id, date=DAY, status=status,
        )
        Attendance.objects.filter(pk=obj.pk).update(created_at=created_at)
        return obj.pk

    t = datetime.datetime(2026, 9, 24, 5, 0, tzinfo=datetime.timezone.utc)
    # Slot 1: three rows at distinct times; the newest wins.
    row(session.id, 'present', t)
    row(session.id, 'absent', t + datetime.timedelta(minutes=5))
    newest = row(session.id, 'present', t + datetime.timedelta(minutes=9))
    # Slot 2: a tie on created_at; the higher id wins.
    tied_low = row(other_session.id, 'absent', t)
    tied_high = row(other_session.id, 'present', t)
    assert tied_high > tied_low

    new_apps = migrate_to(AFTER)
    Attendance = new_apps.get_model('lesson', 'ScheduleAttendance')

    survivors = dict(
        Attendance.objects.filter(student_id=student.id)
        .values_list('session_id', 'id')
    )
    assert survivors == {session.id: newest, other_session.id: tied_high}
    assert Attendance.objects.filter(student_id=student.id).count() == 2
    # AC-12: rows that predate the audit columns carry no marker.
    assert not Attendance.objects.filter(
        student_id=student.id, marked_by__isnull=False,
    ).exists()
    assert not Attendance.objects.filter(
        student_id=student.id, updated_at__isnull=False,
    ).exists()
    assert 'deleted 3 duplicate' in capsys.readouterr().out
