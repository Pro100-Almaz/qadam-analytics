"""§7: the one constraint change tenancy requires.

`PsychologicalStateTemplates.name` was globally unique, which means school #2
cannot create a template whose name school #1 already used — one tenant
blocking another it cannot even see. Dropping the global unique in favour of
unique(school, name) is a *relaxation*, so it cannot fail on existing data.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0040_school_not_null"),
    ]

    operations = [
        migrations.AlterField(
            model_name="psychologicalstatetemplates",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AddConstraint(
            model_name="psychologicalstatetemplates",
            constraint=models.UniqueConstraint(
                fields=("school", "name"),
                name="psychstatetemplate_unique_name_per_school",
            ),
        ),
    ]
