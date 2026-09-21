"""Shared entry-point plumbing for the scripts in `scripts/`.

Every script that writes tenant data has to answer one question the ORM can no
longer answer for it: **which school?** Before tenancy there was no such
question; `scripts/users/custom_user_XLS.py` guessed it per row from a
spreadsheet column:

    school_name = row['School'].lower().strip()
    if 'alim' in school_name:
        school_name = 'muzafar_alimbayev'
    else:
        school_name = 'bukhar_zhyrau'

That heuristic is how user id=2 ended up alone in an empty tenant with all of
their academic data in the other one. It is deleted, not fixed: a required
`--school` flag makes the answer explicit, one import file per school, and
impossible to get silently wrong.

Usage::

    from scripts.utils.bootstrap import setup_django, school_from_argv

    setup_django()
    school, args = school_from_argv('Import users from the roster sheet.')
    with school_scope(school):
        ...
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup_django():
    """Put the repo on sys.path and boot Django. Idempotent."""
    if BASE_DIR not in sys.path:
        sys.path.append(BASE_DIR)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    import django
    from django.apps import apps
    if not apps.ready:
        django.setup()


def add_school_argument(parser):
    parser.add_argument(
        '--school', required=True,
        help=(
            'Slug of the school these rows belong to. Required, never inferred '
            'from the data: guessing it per row is what stranded a user in the '
            'wrong tenant. Run the script once per school.'
        ),
    )
    return parser


def resolve_school(slug):
    """A School instance, or a clear exit rather than a traceback."""
    from apps.authentication.models import School

    school = School.objects.filter(slug=slug).first()
    if school is None:
        known = ', '.join(School.objects.values_list('slug', flat=True)) or '(none)'
        sys.exit(f'No school with slug {slug!r}. Known slugs: {known}')
    return school


def school_from_argv(description, configure=None):
    """Parse `--school` (plus whatever `configure` adds) and resolve it."""
    parser = add_school_argument(argparse.ArgumentParser(description=description))
    if configure is not None:
        configure(parser)
    args = parser.parse_args()
    return resolve_school(args.school), args


def active_school():
    """The School the surrounding `school_scope(...)` names.

    For write sites. Reads narrow by themselves — `Model.objects` is scoped —
    but a `create()` still has to put a value in a NOT NULL `school` column,
    and threading the School object down through every helper in a script that
    predates tenancy is a lot of signature churn for one value that is already
    in the context.

    Fails loudly outside a scope rather than returning None: a script that
    forgot `with school_scope(school):` would otherwise write rows with no
    tenant, which is exactly the class of bug `--school` exists to prevent.
    """
    from apps.authentication.models import School
    from core.tenancy import get_active_school

    scope = get_active_school()
    if not isinstance(scope, int):
        sys.exit(
            'No active school scope. Wrap the work in '
            '`with school_scope(school):` — see school_from_argv().'
        )
    return School.objects.get(pk=scope)
