"""`AcademicYear.school` becomes NOT NULL, and the year constraints land.

A SEPARATE migration from the backfill, per §6: land the split, verify

    SELECT count(*) FROM home_academicyear WHERE school_id IS NULL;   -- 0

and only then constrain. A backfill that silently no-ops makes this AlterField
hit a not-null violation and Django rolls the transaction back, so the failure
mode is a refused deploy rather than a table full of orphans.

The two constraints are the §7 pair, restored to their per-school shape now
that the column exists again:

* `unique(school, year)` — both schools may name `2025/2026`, neither twice.
  This is a *relaxation* of the `unique(year)` the shared row implied.
* one active year per school — `filter(is_active=True).first()` is used as a
  singleton in ~24 places, and without this a half-finished rollover makes it
  nondeterministic. The split copies `is_active` verbatim, so each school ends
  up with exactly as many active rows as there were before: one.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0038_academicyear_school'),
    ]

    operations = [
        migrations.AlterField(
            model_name='academicyear',
            name='school',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='academic_years',
                to='authentication.school',
            ),
        ),
        migrations.AlterModelOptions(
            name='academicyear',
            options={
                'verbose_name': 'Учебный год',
                'verbose_name_plural': 'Учебные годы',
            },
        ),
        migrations.AddConstraint(
            model_name='academicyear',
            constraint=models.UniqueConstraint(
                fields=('school', 'year'),
                name='academicyear_unique_year_per_school',
            ),
        ),
        migrations.AddConstraint(
            model_name='academicyear',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_active', True)),
                fields=('school',),
                name='academicyear_one_active_per_school',
            ),
        ),
    ]
