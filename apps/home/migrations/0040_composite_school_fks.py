"""§7 layer 3: cross-tenant integrity enforced by Postgres itself.

Layers 1 and 2 (`SchoolConsistentModel`, the m2m guard) live in Python, so
they hold for anything that goes through the ORM's save path and nothing else.
A `bulk_create`, a `QuerySet.update`, a psql session or a script written in a
hurry all walk straight past them. These three foreign keys are the layer that
survives all of that:

    home_subjectoffering (subject_id,      school_id) -> home_subject
    home_subjectoffering (class_group_id,  school_id) -> home_classgroup
    home_classgroup      (academic_year_id, school_id) -> home_academicyear

`SubjectOffering` is exactly why §1 gave it a denormalised `school` column in
the first place: it is the hub every lesson and grade funnels through, and the
one row where school A's Subject can be married to school B's ClassGroup.

Two Postgres details this relies on:

* The referenced columns need a UNIQUE index, which is what the three
  `AddConstraint` operations above create. `id` alone is already unique, so
  those add no new rule about the data — they exist to give these FKs a target.
* `ClassGroup.academic_year` is nullable, and the default MATCH SIMPLE means a
  composite FK with any NULL column is simply not checked. That is the
  behaviour we want: a class group with no year stays legal.

DEFERRABLE INITIALLY DEFERRED so that a transaction may reorder rows mid-way —
the §1b year split moved children between year copies inside one transaction,
and an immediate constraint would have fired on the first UPDATE of a pair.

The pre-check is not decoration. On the production data at the time of writing,
school #2's two offerings pointed at school #1's Kazakh subjects, so this
migration *will* fail there — and it should. Re-pointing an offering at the
right subject is a data decision, not something a migration may guess at, so
the check names the offending rows and stops.
"""

from django.conf import settings
from django.db import migrations, models

VIOLATION_QUERIES = (
    (
        'SubjectOffering.subject',
        """
        SELECT o.id, o.school_id, s.school_id
        FROM home_subjectoffering o
        JOIN home_subject s ON s.id = o.subject_id
        WHERE o.school_id <> s.school_id
        """,
    ),
    (
        'SubjectOffering.class_group',
        """
        SELECT o.id, o.school_id, c.school_id
        FROM home_subjectoffering o
        JOIN home_classgroup c ON c.id = o.class_group_id
        WHERE o.school_id <> c.school_id
        """,
    ),
    (
        'ClassGroup.academic_year',
        """
        SELECT c.id, c.school_id, y.school_id
        FROM home_classgroup c
        JOIN home_academicyear y ON y.id = c.academic_year_id
        WHERE c.school_id <> y.school_id
        """,
    ),
)


def refuse_existing_cross_tenant_rows(apps, schema_editor):
    """Fail with the offending rows rather than a bare FK violation."""
    problems = []
    with schema_editor.connection.cursor() as cursor:
        for label, sql in VIOLATION_QUERIES:
            cursor.execute(sql)
            rows = cursor.fetchall()
            if rows:
                problems.append(
                    f'{label}: {len(rows)} row(s) cross schools — '
                    + ', '.join(
                        f'id={row[0]} (row school #{row[1]}, parent school #{row[2]})'
                        for row in rows[:20]
                    )
                    + ('…' if len(rows) > 20 else '')
                )
    if problems:
        raise RuntimeError(
            'Cannot add the composite school foreign keys: rows already point '
            'across tenants.\n' + '\n'.join(problems) + '\n'
            'Re-point each row at its own school\'s parent (in /admin/, with '
            'the school switcher) and run the migration again. Which parent is '
            'correct is a data decision; this migration will not guess.'
        )


def noop(apps, schema_editor):
    """Nothing to undo — the check writes nothing."""


COMPOSITE_FKS = (
    (
        'home_subjectoffering', 'offering_subject_same_school',
        '(subject_id, school_id)', 'home_subject (id, school_id)',
    ),
    (
        'home_subjectoffering', 'offering_class_group_same_school',
        '(class_group_id, school_id)', 'home_classgroup (id, school_id)',
    ),
    (
        'home_classgroup', 'classgroup_academic_year_same_school',
        '(academic_year_id, school_id)', 'home_academicyear (id, school_id)',
    ),
)


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0041_psychstatetemplate_unique_name_per_school"),
        ("home", "0039_academicyear_school_not_null"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="academicyear",
            constraint=models.UniqueConstraint(
                fields=("id", "school"), name="academicyear_id_school_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="classgroup",
            constraint=models.UniqueConstraint(
                fields=("id", "school"), name="classgroup_id_school_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="subject",
            constraint=models.UniqueConstraint(
                fields=("id", "school"), name="subject_id_school_unique"
            ),
        ),
        migrations.RunPython(refuse_existing_cross_tenant_rows, noop),
    ] + [
        migrations.RunSQL(
            sql=(
                f'ALTER TABLE {table} ADD CONSTRAINT {name} '
                f'FOREIGN KEY {columns} REFERENCES {target} '
                f'DEFERRABLE INITIALLY DEFERRED;'
            ),
            reverse_sql=f'ALTER TABLE {table} DROP CONSTRAINT {name};',
        )
        for table, name, columns, target in COMPOSITE_FKS
    ]
