"""Spec 0005: drop the old category code column and put the FK in its place. See 0041."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0042_assignment_category_copy'),
    ]

    operations = [
        # Reversing re-adds `category` with this default, then copy_fk_to_code
        # overwrites it with each row's real code.
        migrations.RemoveField(
            model_name='subjectassignment',
            name='category',
        ),
        migrations.RenameField(
            model_name='subjectassignment',
            old_name='category_ref',
            new_name='category',
        ),
        migrations.AlterField(
            model_name='subjectassignment',
            name='category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='assignments', to='home.assignmentcategory',
            ),
        ),

        migrations.AddField(
            model_name='subjectassignment',
            name='detail_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subjectassignment',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddConstraint(
            model_name='subjectassignment',
            constraint=models.UniqueConstraint(
                condition=models.Q(('detail_id__isnull', False)),
                fields=('category', 'detail_id'),
                name='subjectassignment_unique_detail',
            ),
        ),
    ]
