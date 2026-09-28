"""One attendance row per lesson slot, plus who last marked it (spec 0004).

The constraint cannot be added while a slot `(session, student, date)` holds
more than one row, so a data step collapses duplicates first: per slot it keeps
the row with the latest `created_at` (the highest `id` breaks a tie) and
deletes the rest, printing how many went.

**The data step is irreversible.** Reversing this migration drops the
constraint and the two audit columns, but deleted duplicates do not come back.
Production had none on 2026-09-25; take a dump of lesson_scheduleattendance
before deploying anyway.

`marked_by` and `updated_at` are added nullable with no backfill: rows saved
before this migration have no recorded marker.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def collapse_duplicates(apps, schema_editor):
    table = apps.get_model('lesson', 'ScheduleAttendance')._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"""
            DELETE FROM {table}
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY session_id, student_id, date
                        ORDER BY created_at DESC, id DESC
                    ) AS position
                    FROM {table}
                ) ranked
                WHERE position > 1
            )
        """)
        deleted = cursor.rowcount
    print(f'\n  lesson.0028: deleted {deleted} duplicate attendance row(s)')


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0043_student_intake_year'),
        ('lesson', '0027_school_not_null'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduleattendance',
            name='marked_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        # Added plain, then altered to auto_now: AddField fills existing rows
        # with the effective default, which for an auto_now field is the
        # migration's own timestamp. Old rows must stay null (AC-12).
        migrations.AddField(
            model_name='scheduleattendance',
            name='updated_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='scheduleattendance',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(collapse_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='scheduleattendance',
            constraint=models.UniqueConstraint(fields=('session', 'student', 'date'), name='scheduleattendance_one_per_slot'),
        ),
    ]
