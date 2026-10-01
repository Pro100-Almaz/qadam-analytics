"""
Spec 0006: AssignmentCategory.name in en / ru / kk (django-modeltranslation).

Adds one column per language, then fills them: every existing name becomes the
English name (AC-5), and the four categories the code base seeds get their
Russian and Kazakh names. A category an admin added before this migration has
only English until someone fills in the rest in /admin/.
"""

from django.db import migrations, models

#: Frozen copy of AssignmentCategory.BUILTIN_NAMES as of this migration.
BUILTIN_NAMES = {
    'lesson': {'name_en': 'Lesson', 'name_ru': 'Урок', 'name_kk': 'Сабақ'},
    'exam': {'name_en': 'Exam', 'name_ru': 'Экзамен', 'name_kk': 'Емтихан'},
    'final': {'name_en': 'Final', 'name_ru': 'Итоговая работа', 'name_kk': 'Қорытынды жұмыс'},
    'homework': {'name_en': 'Homework', 'name_ru': 'Домашнее задание', 'name_kk': 'Үй жұмысы'},
}


def fill_translations(apps, schema_editor):
    AssignmentCategory = apps.get_model('home', 'AssignmentCategory')
    for category in AssignmentCategory.objects.all():
        category.name_en = category.name_en or category.name
        builtin = BUILTIN_NAMES.get(category.code, {})
        category.name_ru = category.name_ru or builtin.get('name_ru')
        category.name_kk = category.name_kk or builtin.get('name_kk')
        category.save(update_fields=['name_en', 'name_ru', 'name_kk'])


def restore_name(apps, schema_editor):
    AssignmentCategory = apps.get_model('home', 'AssignmentCategory')
    for category in AssignmentCategory.objects.exclude(name_en=None):
        category.name = category.name_en
        category.save(update_fields=['name'])


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0043_assignment_category_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='assignmentcategory',
            name='name_en',
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='assignmentcategory',
            name='name_kk',
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='assignmentcategory',
            name='name_ru',
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.RunPython(fill_translations, restore_name),
    ]
