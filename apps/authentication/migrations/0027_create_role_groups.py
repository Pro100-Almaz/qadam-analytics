from django.db import migrations

GROUPS = ['Admin', 'Teacher', 'HomeroomTeacher', 'Student', 'Supervisor', 'Principal', 'Parent']


def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


def reverse(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('authentication', '0026_student_academic_year'),
    ]

    operations = [
        migrations.RunPython(create_groups, reverse),
    ]
