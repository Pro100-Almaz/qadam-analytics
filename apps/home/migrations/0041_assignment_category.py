"""
Spec 0005: SubjectAssignment.category becomes a FK to an admin-managed
AssignmentCategory table, and gains `detail_id` / `is_active`.

The CharField is converted in place: a nullable FK is added beside it, filled
from the old code, the old column dropped and the FK renamed and made NOT NULL.
Every existing row keeps its category (AC-4). Reversible: going back copies the
code into a CharField again.

Split in three because Postgres refuses to ALTER a table in the same
transaction that updated its rows with deferred FK checks still pending:
0041 creates and adds, 0042 copies, 0043 swaps the columns.
"""

import django.db.models.deletion
from django.db import migrations, models

#: (code, name), in the order the original CATEGORY_CHOICES listed them, then
#: the new `homework`. The ids this produces fix the order analytics use.
SEED = [
    ('lesson', 'Lesson'),
    ('exam', 'Exam'),
    ('final', 'Final'),
    ('homework', 'Homework'),
]


def seed_categories(apps, schema_editor):
    AssignmentCategory = apps.get_model('home', 'AssignmentCategory')
    for code, name in SEED:
        AssignmentCategory.objects.get_or_create(code=code, defaults={'name': name})


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0040_composite_school_fks'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssignmentCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(unique=True)),
                ('name', models.CharField(max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name_plural': 'assignment categories',
                'ordering': ['name'],
            },
        ),
        migrations.RunPython(seed_categories, migrations.RunPython.noop),

        # CharField -> FK, preserving every row's category.
        migrations.AddField(
            model_name='subjectassignment',
            name='category_ref',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='+', to='home.assignmentcategory',
            ),
        ),
    ]
