import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Reshape the constellation: one class, many shared подгруппы.

    The `ClassGroup.collection` foreign key could only ever put a subgroup in
    one constellation. A subgroup is shared — 7A and 7B can both run «English
    Advanced» — so the link becomes many-to-many, and the single class each
    constellation belongs to moves onto the constellation itself.
    """

    dependencies = [
        ("home", "0033_minorclassgroup"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="classgroup",
            name="collection",
        ),
        migrations.AlterModelOptions(
            name="classgroupcollection",
            options={
                "verbose_name": "Созвездие класса",
                "verbose_name_plural": "Созвездия классов",
            },
        ),
        migrations.AddField(
            model_name="classgroupcollection",
            name="major",
            field=models.OneToOneField(
                limit_choices_to={"category": "major"},
                on_delete=django.db.models.deletion.CASCADE,
                related_name="collection",
                to="home.classgroup",
                verbose_name="Класс",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="classgroupcollection",
            name="minor_groups",
            field=models.ManyToManyField(
                blank=True,
                limit_choices_to={"category": "minor"},
                related_name="collections",
                to="home.classgroup",
                verbose_name="Подгруппы",
            ),
        ),
    ]
