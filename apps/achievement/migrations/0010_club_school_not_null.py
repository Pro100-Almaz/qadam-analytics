"""Tighten Club.school to NOT NULL — deploy AFTER verifying 0009's backfill.

    SELECT count(*) FROM achievement_club WHERE school_id IS NULL;  -- must be 0

If the backfill no-opped, this ALTER fails and the transaction rolls back. The
failure mode is a refused deploy, not silent corruption.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("achievement", "0009_club_school")]

    operations = [
        migrations.AlterField(
            model_name="club",
            name="school",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clubs",
                to="authentication.school",
            ),
        ),
    ]
