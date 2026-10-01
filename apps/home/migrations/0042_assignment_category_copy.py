"""Spec 0005: fill SubjectAssignment.category_ref from the old code. See 0041."""

from django.db import migrations


def copy_code_to_fk(apps, schema_editor):
    AssignmentCategory = apps.get_model('home', 'AssignmentCategory')
    SubjectAssignment = apps.get_model('home', 'SubjectAssignment')

    # A code outside the old choices can only come from a write that skipped
    # validation; keep it rather than lose the row's meaning.
    for code in SubjectAssignment.objects.values_list('category', flat=True).distinct():
        AssignmentCategory.objects.get_or_create(code=code, defaults={'name': code.title()})

    for category in AssignmentCategory.objects.all():
        SubjectAssignment.objects.filter(category=category.code).update(
            category_ref=category,
        )


def copy_fk_to_code(apps, schema_editor):
    AssignmentCategory = apps.get_model('home', 'AssignmentCategory')
    SubjectAssignment = apps.get_model('home', 'SubjectAssignment')
    for category in AssignmentCategory.objects.all():
        SubjectAssignment.objects.filter(category_ref=category).update(
            category=category.code,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0041_assignment_category'),
    ]

    operations = [
        migrations.RunPython(copy_code_to_fk, copy_fk_to_code),
    ]
