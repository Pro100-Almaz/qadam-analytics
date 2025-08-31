from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lesson', '0005_remove_studentgrade_lesson_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='topic',
            name='title',
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
