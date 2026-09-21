from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0032_classgroupcollection_classgroup_collection"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="classgroup",
            options={"verbose_name": "Класс", "verbose_name_plural": "Классы"},
        ),
        migrations.AlterField(
            model_name="classgroup",
            name="letter",
            field=models.CharField(default="A", max_length=50),
        ),
        migrations.CreateModel(
            name="MinorClassGroup",
            fields=[],
            options={
                "verbose_name": "Подгруппа",
                "verbose_name_plural": "Подгруппы",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("home.classgroup",),
        ),
    ]
