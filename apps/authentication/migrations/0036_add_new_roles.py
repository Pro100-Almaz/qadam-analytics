from django.db import migrations

GROUPS = [
    'Admin',
    'Teacher',
    'HomeroomTeacher',
    'Student',
    'Supervisor',
    'Principal',
    'Parent',
    'Psychologist',
    'ClubManager'
]


def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ('authentication', '0035_historicalstudent_medical_features_and_more'),
    ]

    operations = [
        migrations.RunPython(create_groups, reverse),
    ]
