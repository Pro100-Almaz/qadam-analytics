"""Convert CustomUser.school from a CharField label into a School FK.

Done as rename + add + backfill rather than a direct AlterField: Postgres would
emit `ALTER COLUMN school TYPE bigint USING school::bigint`, and
`'muzafar_alimbayev'::bigint` raises. The old column survives as
`legacy_school` until Phase 7 so the conversion stays reversible.
"""

import django.db.models.deletion
from django.db import migrations, models


def backfill_user_school(apps, schema_editor):
    """Put EVERY existing user in school #1 — deliberately ignoring legacy_school.

    Do not be tempted to map the legacy string. Exactly one row carries
    'bukhar_zhyrau', assigned by the `'alim' in name` guess at
    scripts/users/custom_user_XLS.py:144-152, and all of that user's academic
    data (enrollments, grades) lives in school #1. Honouring the string would
    strand them alone in an empty tenant, invisible to everybody, with their
    grades in the other school. The second school is not live yet, so school #1
    is the correct home for all existing data.
    """
    School = apps.get_model('authentication', 'School')
    CustomUser = apps.get_model('authentication', 'CustomUser')

    school = School.objects.filter(slug='muzafar_alimbayev').first()
    if school is None:                      # fresh DB with no seeded tenants
        return
    CustomUser.objects.update(school=school)


def unbackfill_user_school(apps, schema_editor):
    CustomUser = apps.get_model('authentication', 'CustomUser')
    CustomUser.objects.update(school=None)


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0037_school"),
    ]

    operations = [
        migrations.RenameField(
            model_name="customuser",
            old_name="school",
            new_name="legacy_school",
        ),
        migrations.AlterField(
            model_name="customuser",
            name="legacy_school",
            field=models.CharField(
                choices=[
                    ("muzafar_alimbayev", "Muzafar Alimbayev 21"),
                    ("bukhar_zhyrau", "Bukhar Zhyrau 19/1"),
                ],
                default="muzafar_alimbayev",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="customuser",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text="The tenant this user belongs to. Exactly one, except superusers.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="authentication.school",
            ),
        ),
        migrations.RunPython(backfill_user_school, unbackfill_user_school),
    ]
