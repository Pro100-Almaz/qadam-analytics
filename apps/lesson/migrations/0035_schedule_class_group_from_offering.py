"""Spec 0018 AC-1 — an offering-bound schedule's class group is its offering's.

Production had drifted: rows created before `0024` added the column carry
NULL, and some later rows name a different class group (usually a подгруппа
of the offering's class). Both are overwritten from the offering. Free
entries (no offering) keep their own class group.
"""

from django.db import migrations
from django.db.models import OuterRef, Q, Subquery


def align_with_offering(apps, schema_editor):
    SubjectSchedule = apps.get_model('lesson', 'SubjectSchedule')
    SubjectOffering = apps.get_model('home', 'SubjectOffering')
    # `_base_manager`: every row, soft-deleted included, with no school scope.
    SubjectSchedule._base_manager.filter(offering__isnull=False).filter(
        Q(class_group__isnull=True)
        | ~Q(class_group_id=Subquery(
            SubjectOffering._base_manager.filter(
                pk=OuterRef('offering_id'),
            ).values('class_group_id')[:1]
        ))
    ).update(
        class_group_id=Subquery(
            SubjectOffering._base_manager.filter(
                pk=OuterRef('offering_id'),
            ).values('class_group_id')[:1]
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("lesson", "0034_remove_homework_teaching_assignment"),
    ]

    operations = [
        # Reverse is a no-op: the previous values were wrong and are not kept.
        migrations.RunPython(align_with_offering, migrations.RunPython.noop),
    ]
