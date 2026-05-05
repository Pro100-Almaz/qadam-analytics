from django.core.management.base import BaseCommand
from django.db import transaction

from apps.home.models import AcademicYear, ClassGroup, GradeLevel, Enrollment


class Command(BaseCommand):
    help = 'Roll over to a new academic year: create year, promote students, archive enrollments.'

    def add_arguments(self, parser):
        parser.add_argument('new_year_name', type=str, help='e.g., 2026-2027')
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        new_year_name = options['new_year_name']

        try:
            with transaction.atomic():
                summary = self._rollover(new_year_name)

                for line in summary:
                    self.stdout.write(line)

                if dry_run:
                    self.stdout.write(self.style.WARNING('\nDRY RUN — rolling back all changes'))
                    raise _DryRunRollback()

            self.stdout.write(self.style.SUCCESS(f'\nRolled over to {new_year_name}'))

        except _DryRunRollback:
            pass

    def _rollover(self, new_year_name):
        summary = []

        current_year = AcademicYear.objects.filter(is_active=True).first()
        if not current_year:
            self.stderr.write(self.style.ERROR('No active academic year found.'))
            return []

        new_year, created = AcademicYear.objects.get_or_create(
            year=new_year_name,
            defaults={'is_active': True, 'archived': False},
        )
        if not created:
            self.stderr.write(self.style.ERROR(f'Academic year {new_year_name} already exists.'))
            return []

        current_year.is_active = False
        current_year.archived = True
        current_year.save(update_fields=['is_active', 'archived'])
        summary.append(f'Archived {current_year.year}, created {new_year_name}')

        old_class_groups = ClassGroup.objects.filter(
            academic_year=current_year,
        ).select_related('grade_level')

        group_mapping = {}
        for old_cg in old_class_groups:
            if not old_cg.grade_level:
                continue

            next_grade_number = old_cg.grade_level.number + 1
            next_grade, _ = GradeLevel.objects.get_or_create(number=next_grade_number)

            new_cg, _ = ClassGroup.objects.get_or_create(
                academic_year=new_year,
                grade_level=next_grade,
                letter=old_cg.letter,
            )
            group_mapping[old_cg.id] = new_cg

        summary.append(f'Created {len(group_mapping)} class groups for {new_year_name}')

        active_enrollments = Enrollment.objects.filter(
            academic_year=current_year,
            status='active',
        ).select_related('student', 'class_group')

        promoted = 0
        graduated = 0
        for enrollment in active_enrollments:
            new_cg = group_mapping.get(enrollment.class_group_id)

            enrollment.status = 'graduated' if new_cg is None else 'transferred'
            enrollment.save(update_fields=['status'])

            if new_cg is None:
                graduated += 1
                continue

            Enrollment.objects.create(
                student=enrollment.student,
                class_group=new_cg,
                academic_year=new_year,
                status='active',
            )
            promoted += 1

        summary.append(f'Promoted {promoted} students, graduated {graduated}')
        summary.append('Subject offerings left empty — reassign teachers manually')

        return summary


class _DryRunRollback(Exception):
    pass
