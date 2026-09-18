"""AcademicYear becomes shared across all schools (§1a).

Reverses the phase-1 decision that years are per-school, after confirming both
schools follow the same national calendar: one 2025/2026 row with one set of
quarter dates serves both, and `filter(is_active=True).first()` becomes a
correct global singleton rather than an ambiguous one.

Nothing to merge: the two existing rows both belong to school #1, so dropping
the column loses no information. Had school #2 owned years of its own they
would have had to be reconciled by hand first — a `RemoveField` would silently
collapse duplicates into one.

Ordering: this must land in the same release as the six SCHOOL_PATH rewrites
that used to route through `academic_year__school`, or `manage.py check` fails
tenancy.E003 in between.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0036_school_not_null"),
        ("achievement", "0010_club_school_not_null"),
    ]

    operations = [
        migrations.RemoveField(model_name="academicyear", name="school"),
    ]
