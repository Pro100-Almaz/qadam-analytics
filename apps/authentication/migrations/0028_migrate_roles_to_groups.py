from django.db import migrations

ROLE_TO_GROUP = {
    'admin': 'Admin',
    'teacher': 'Teacher',
    'homeroom_teacher': 'HomeroomTeacher',
    'student': 'Student',
    'supervisor': 'Supervisor',
    'principal': 'Principal',
    'parent': 'Parent',
}


def migrate_roles_to_groups(apps, schema_editor):
    CustomUser = apps.get_model('authentication', 'CustomUser')
    Group = apps.get_model('auth', 'Group')

    # Cache groups for efficiency
    groups = {g.name: g for g in Group.objects.filter(name__in=ROLE_TO_GROUP.values())}

    for user in CustomUser.objects.all():
        group_name = ROLE_TO_GROUP.get(user.role)
        if group_name and group_name in groups:
            user.groups.add(groups[group_name])


def reverse(apps, schema_editor):
    CustomUser = apps.get_model('authentication', 'CustomUser')
    Group = apps.get_model('auth', 'Group')

    group_names = list(ROLE_TO_GROUP.values())
    groups = Group.objects.filter(name__in=group_names)

    for user in CustomUser.objects.all():
        user.groups.remove(*groups)


class Migration(migrations.Migration):
    dependencies = [
        ('authentication', '0027_create_role_groups'),
    ]

    operations = [
        migrations.RunPython(migrate_roles_to_groups, reverse),
    ]
