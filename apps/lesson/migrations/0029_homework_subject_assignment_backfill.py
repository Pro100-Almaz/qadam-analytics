"""
Spec 0005 AC-12: mirror every existing Homework as a SubjectAssignment of
category `homework`, and every HomeworkGrade as a SubjectGrade on it.

From here on the model save()/delete() hooks keep the two in step
(apps/lesson/homework_sync.py); this only brings the rows that predate them
up to the same state. Historical models carry no hooks, so nothing echoes.
Reversing deletes the mirrors — their grades cascade with them.
"""

from django.db import migrations


def mirror_homework(apps, schema_editor):
    AssignmentCategory = apps.get_model('home', 'AssignmentCategory')
    SubjectAssignment = apps.get_model('home', 'SubjectAssignment')
    SubjectGrade = apps.get_model('home', 'SubjectGrade')
    Homework = apps.get_model('lesson', 'Homework')
    HomeworkGrade = apps.get_model('lesson', 'HomeworkGrade')

    category, _ = AssignmentCategory.objects.get_or_create(
        code='homework', defaults={'name': 'Homework'},
    )
    already = set(
        SubjectAssignment.objects.filter(category=category)
        .values_list('detail_id', flat=True)
    )

    mirrors = {}
    for homework in Homework.objects.order_by('pk').iterator():
        if homework.pk in already:
            continue
        mirrors[homework.pk] = SubjectAssignment.objects.create(
            category=category,
            detail_id=homework.pk,
            offering_id=homework.offering_id,
            title=homework.description,
            max_grade=homework.max_grade,
            date=homework.due_date,
            is_active=homework.is_active,
        )

    SubjectGrade.objects.bulk_create([
        SubjectGrade(
            assignment=mirrors[grade.homework_id],
            student_id=grade.student_id,
            grade=grade.grade,
            comments=grade.comments,
        )
        for grade in HomeworkGrade.objects.filter(
            homework_id__in=list(mirrors),
        ).iterator()
    ], batch_size=500)


def drop_mirrors(apps, schema_editor):
    SubjectAssignment = apps.get_model('home', 'SubjectAssignment')
    SubjectAssignment.objects.filter(category__code='homework').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0043_assignment_category_fk'),
        ('lesson', '0028_scheduleattendance_one_per_slot'),
    ]

    operations = [
        migrations.RunPython(mirror_homework, drop_mirrors),
    ]
