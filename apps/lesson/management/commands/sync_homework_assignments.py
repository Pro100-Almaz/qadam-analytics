"""
Check (and optionally repair) the Homework <-> SubjectAssignment mirror.

    python manage.py sync_homework_assignments --check   # exit 1 on any drift
    python manage.py sync_homework_assignments --fix     # rewrite from Homework

The model hooks keep both sides in step on every save()/delete(); this is the
safety net for writes they cannot see — QuerySet.update()/delete(), cascades
from a deleted Teacher, raw SQL. Spans every school: the mirror is per row, not
per tenant. See apps/lesson/homework_sync.py and spec 0005.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.lesson import homework_sync
from core.tenancy import all_schools


class Command(BaseCommand):
    help = 'Report or repair drift between Homework and its SubjectAssignment mirror.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            '--check', action='store_true',
            help='Report drift and exit non-zero if there is any (default).',
        )
        mode.add_argument(
            '--fix', action='store_true',
            help='Rewrite the mirror from Homework, which is the source of truth.',
        )

    def handle(self, *args, **options):
        with all_schools():
            if options['fix']:
                problems = homework_sync.fix_drift()
                for problem in problems:
                    self.stdout.write(f'fixed  {problem.kind:<22} {problem.detail}')
                self.stdout.write(self.style.SUCCESS(
                    f'{len(problems)} problem(s) fixed.' if problems else 'In sync.'
                ))
                return

            problems = homework_sync.find_drift()
        for problem in problems:
            self.stdout.write(f'{problem.kind:<22} {problem.detail}')
        if problems:
            raise CommandError(
                f'{len(problems)} problem(s). Run with --fix to repair from Homework.'
            )
        self.stdout.write(self.style.SUCCESS('In sync.'))
