"""AcademicYear becomes per-school again, splitting the shared rows.

This reverses `0037_academicyear_shared`, and it is **not** the inverse of it.
`RemoveField` was lossless because every row belonged to one school; putting
the column back means each shared row has to become one row *per school*, with
every child re-pointed at the copy matching its own school.

Which copy keeps the original pk matters more than it looks: a pk that already
escaped the database — a link someone bookmarked, a report queued with a year
id, anything the frontend stored — stays valid only for the school that keeps
it. So the original goes to whichever school references it most, and only the
smaller side is re-pointed. On the dev data that is 107 rows moved instead of
~450.

Seven tables reference a year. Five are NOT NULL, two are nullable:

    home_classgroup.academic_year_id                (nullable)
    authentication_student.academic_year_id         (nullable)
    achievement_achievement.academic_year_id
    achievement_club.academic_year_id
    achievement_clubentry.academic_year_id
    achievement_readingentry.academic_year_id
    student_report_studentreport.academic_year_id

Each is re-pointed through its own route to a school, never through the year —
that is the whole point, since the year is what is ambiguous here.
"""

from django.db import migrations, models
import django.db.models.deletion


#: (table, how to reach the owning school from a row of it). Each query yields
#: (row id, school id) pairs, and every join is over a NOT NULL FK except the
#: `academic_year_id IS NOT NULL` guard, which only skips rows with no year.
CHILDREN = {
    'home_classgroup': """
        SELECT id, school_id FROM home_classgroup
        WHERE academic_year_id IS NOT NULL
    """,
    'authentication_student': """
        SELECT s.id, u.school_id
        FROM authentication_student s
        JOIN authentication_customuser u ON u.id = s.user_id
        WHERE s.academic_year_id IS NOT NULL AND u.school_id IS NOT NULL
    """,
    'achievement_achievement': """
        SELECT a.id, u.school_id
        FROM achievement_achievement a
        JOIN authentication_student s ON s.id = a.student_id
        JOIN authentication_customuser u ON u.id = s.user_id
        WHERE u.school_id IS NOT NULL
    """,
    'achievement_club': """
        SELECT id, school_id FROM achievement_club
    """,
    'achievement_clubentry': """
        SELECT c.id, u.school_id
        FROM achievement_clubentry c
        JOIN authentication_student s ON s.id = c.student_id
        JOIN authentication_customuser u ON u.id = s.user_id
        WHERE u.school_id IS NOT NULL
    """,
    'achievement_readingentry': """
        SELECT r.id, u.school_id
        FROM achievement_readingentry r
        JOIN authentication_student s ON s.id = r.student_id
        JOIN authentication_customuser u ON u.id = s.user_id
        WHERE u.school_id IS NOT NULL
    """,
    'student_report_studentreport': """
        SELECT sr.id, u.school_id
        FROM student_report_studentreport sr
        JOIN authentication_student s ON s.id = sr.student_id
        JOIN authentication_customuser u ON u.id = s.user_id
        WHERE u.school_id IS NOT NULL
    """,
}

YEAR_FIELDS = (
    'year', 'is_active', 'archived',
    'q1_start', 'q1_end', 'q2_start', 'q2_end',
    'q3_start', 'q3_end', 'q4_start', 'q4_end',
)


def split_years_per_school(apps, schema_editor):
    School = apps.get_model('authentication', 'School')
    AcademicYear = apps.get_model('home', 'AcademicYear')
    connection = schema_editor.connection

    school_ids = list(School.objects.order_by('pk').values_list('pk', flat=True))
    if not school_ids:
        return                      # nothing to split into

    years = list(AcademicYear.objects.order_by('pk'))
    if not years:
        return

    # Which school each child row belongs to, per table.
    owners = {}                     # table -> {row id: school id}
    references = {}                 # (year id, school id) -> [(table, row id)]
    with connection.cursor() as cursor:
        for table, sql in CHILDREN.items():
            cursor.execute(sql)
            owners[table] = dict(cursor.fetchall())

        for table in CHILDREN:
            cursor.execute(
                f'SELECT id, academic_year_id FROM {table} '
                f'WHERE academic_year_id IS NOT NULL'
            )
            for row_id, year_id in cursor.fetchall():
                school_id = owners[table].get(row_id)
                if school_id is None:
                    # A row whose own route to a school is broken — a student
                    # profile on a schoolless superuser, say. Leave it on the
                    # original row rather than guess; the NOT NULL migration
                    # that follows is the gate, not this one.
                    continue
                references.setdefault((year_id, school_id), []).append(
                    (table, row_id)
                )

    for year in years:
        users = {
            school_id: len(rows)
            for (year_id, school_id), rows in references.items()
            if year_id == year.pk
        }
        # The original keeps the school that references it most, so the fewest
        # pks change hands. Ties, and a year nobody references, fall to the
        # lowest school id — deterministic either way.
        keeper = max(
            school_ids,
            key=lambda school_id: (users.get(school_id, 0), -school_id),
        )
        AcademicYear.objects.filter(pk=year.pk).update(school_id=keeper)

        for school_id in school_ids:
            if school_id == keeper:
                continue
            copy = AcademicYear.objects.create(
                school_id=school_id,
                **{field: getattr(year, field) for field in YEAR_FIELDS},
            )
            rows = references.get((year.pk, school_id), ())
            by_table = {}
            for table, row_id in rows:
                by_table.setdefault(table, []).append(row_id)
            with connection.cursor() as cursor:
                for table, row_ids in by_table.items():
                    cursor.execute(
                        f'UPDATE {table} SET academic_year_id = %s '
                        f'WHERE id = ANY(%s)',
                        [copy.pk, row_ids],
                    )

    # The §Context trap, hit for real in home/0035: Django runs the new FK's
    # deferred index creation when this migration's schema_editor exits, and
    # Postgres refuses CREATE INDEX while the row updates above still have
    # outstanding deferred-FK trigger events.
    schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def merge_years_back(apps, schema_editor):
    """Reverse: point every child at the lowest-pk row for its year, drop the rest.

    Lossy by nature — per-school quarter dates cannot survive a merge. It exists
    so the migration is runnable backwards in development, not because undoing
    this in production is a good idea.
    """
    AcademicYear = apps.get_model('home', 'AcademicYear')
    connection = schema_editor.connection

    survivors = {}
    for year in AcademicYear.objects.order_by('pk'):
        survivors.setdefault(year.year, year.pk)

    with connection.cursor() as cursor:
        for year in AcademicYear.objects.order_by('pk'):
            keeper = survivors[year.year]
            if keeper == year.pk:
                continue
            for table in CHILDREN:
                cursor.execute(
                    f'UPDATE {table} SET academic_year_id = %s '
                    f'WHERE academic_year_id = %s',
                    [keeper, year.pk],
                )
            AcademicYear.objects.filter(pk=year.pk).delete()

    schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0037_academicyear_shared'),
        ('authentication', '0040_school_not_null'),
        ('achievement', '0010_club_school_not_null'),
        ('student_report', '0002_alter_studentreport_language'),
    ]

    operations = [
        migrations.AddField(
            model_name='academicyear',
            name='school',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='academic_years',
                to='authentication.school',
            ),
        ),
        migrations.RunPython(split_years_per_school, merge_years_back),
    ]
