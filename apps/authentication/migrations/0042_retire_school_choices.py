"""Phase 7: `SCHOOL_CHOICES` retires; `legacy_school` stays.

The column is kept permanently — it is the input the phase-1 backfill read to
decide each user's tenant (`authentication/0038`), and therefore the only
independent record of that decision. What goes is the pair of things that made
it lie about the present:

* `choices` hardcoded the two original schools. A third tenant would make the
  column invalid for its users while telling them nothing.
* `default='muzafar_alimbayev'` stamped school #1's name onto every user
  created after the split, school #2's included. A recovery record that
  invents entries is worse than none.

Existing values are untouched: this is a field-level change only, so every row
backfilled in phase 1 keeps exactly what the legacy column said. Rows created
between the split and this migration still carry the old default — they are
identifiable by having a `school` that disagrees with it, and there is nothing
to repair, only to know about.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0041_psychstatetemplate_unique_name_per_school"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="legacy_school",
            field=models.CharField(
                blank=True, default="", editable=False, max_length=20
            ),
        ),
    ]
