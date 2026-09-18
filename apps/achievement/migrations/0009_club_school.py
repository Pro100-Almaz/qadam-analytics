"""Give Club its own school column (§1a).

AcademicYear became shared, so `academic_year__school` no longer reaches a
tenant. `manager` is the club's only other FK and it is SET_NULL, so a
join-based path would drop every manager-less club from every school. The
column is the only correct answer.

Added nullable and backfilled here; `0010` tightens it to NOT NULL as a
separate operation, so a backfill that silently did nothing fails the ALTER
rather than writing bad data.
"""

import django.db.models.deletion
from django.db import migrations, models


def backfill(apps, schema_editor):
    """Derive from the club's manager, falling back to school #1.

    The fallback is not a guess: every existing row belongs to the one live
    school (see the phase-1 verification), and a manager-less club has no other
    signal to read.
    """
    School = apps.get_model('authentication', 'School')
    school = School.objects.filter(slug='muzafar_alimbayev').first()
    if school is None:                      # fresh DB with no seeded tenants
        return

    Club = apps.get_model('achievement', 'Club')
    for row in Club.objects.select_related('manager__user').iterator():
        derived = None
        if row.manager_id and row.manager.user_id:
            derived = row.manager.user.school_id
        row.school_id = derived or school.pk
        row.save(update_fields=['school'])


def unbackfill(apps, schema_editor):
    apps.get_model('achievement', 'Club').objects.update(school=None)


class Migration(migrations.Migration):

    dependencies = [
        ("achievement", "0008_school_not_null"),
        ("authentication", "0040_school_not_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="club",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clubs",
                to="authentication.school",
            ),
        ),
        migrations.RunPython(backfill, unbackfill),
    ]
