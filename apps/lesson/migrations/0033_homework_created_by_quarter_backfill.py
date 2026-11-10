"""
Spec 0017 AC-17: fill `Homework.created_by` and `Homework.quarter` from the
teaching assignment they replace.

`created_by` is the assignment's teacher. `quarter` is the mirror's, which is
what access was checked against; where the mirror has none (a date outside
every quarter's bounds), the assignment's quarter is used instead, and the
mirror is given the same value so the two agree from here on.

Reversing picks the author's live assignment to the offering for the
homework's quarter, and leaves the FK NULL where there is none.
"""

from django.db import migrations


def fill(apps, schema_editor):
    Homework = apps.get_model('lesson', 'Homework')
    SubjectAssignment = apps.get_model('home', 'SubjectAssignment')

    mirrors = {
        assignment.detail_id: assignment
        for assignment in SubjectAssignment.objects.filter(
            category__code='homework', is_deleted=False,
        )
    }
    for homework in Homework.objects.select_related(
        'teaching_assignment',
    ).order_by('pk').iterator():
        teaching = homework.teaching_assignment
        mirror = mirrors.get(homework.pk)
        quarter = mirror.quarter if mirror is not None else None
        if quarter is None and teaching is not None:
            quarter = teaching.quarter
        homework.created_by_id = teaching.teacher_id if teaching else None
        homework.quarter = quarter
        homework.save(update_fields=['created_by', 'quarter'])
        if mirror is not None and mirror.quarter != quarter:
            mirror.quarter = quarter
            mirror.save(update_fields=['quarter'])


def unfill(apps, schema_editor):
    Homework = apps.get_model('lesson', 'Homework')
    TeachingAssignment = apps.get_model('home', 'TeachingAssignment')

    for homework in Homework.objects.order_by('pk').iterator():
        teaching = None
        if homework.created_by_id is not None and homework.quarter is not None:
            teaching = TeachingAssignment.objects.filter(
                offering_id=homework.offering_id,
                teacher_id=homework.created_by_id,
                quarter=homework.quarter,
                is_deleted=False,
            ).order_by('pk').first()
        homework.teaching_assignment = teaching
        homework.save(update_fields=['teaching_assignment'])


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0050_teachingassignment_unique_offering_quarter_teacher'),
        ('lesson', '0032_homework_created_by_quarter'),
    ]

    operations = [
        migrations.RunPython(fill, unfill),
    ]
