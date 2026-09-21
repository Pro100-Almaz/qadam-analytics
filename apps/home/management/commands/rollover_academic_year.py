from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import School
from apps.home.models import AcademicYear, ClassGroup, GradeLevel, Enrollment
from core.tenancy import school_scope


class Command(BaseCommand):
    help = 'Roll over to a new academic year: create year, promote students, archive enrollments.'

    def add_arguments(self, parser):
        parser.add_argument('new_year_name', type=str, help='e.g., 2026-2027')
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
        parser.add_argument(
            '--school', required=True,
            help=(
                'Slug of the school to roll over. Required, not inferred: '
                'everything a rollover touches — the academic year itself, its '
                'class groups and its enrollments — is per-school, so this runs '
                'once per school and the two need not happen on the same day.'
            ),
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        new_year_name = options['new_year_name']

        try:
            school = School.objects.get(slug=options['school'])
        except School.DoesNotExist:
            known = ', '.join(School.objects.values_list('slug', flat=True))
            raise CommandError(f'No school with slug {options["school"]!r}. Known: {known}')

        try:
            with transaction.atomic(), school_scope(school):
                summary = self._rollover(new_year_name, school)

                for line in summary:
                    self.stdout.write(line)

                if dry_run:
                    self.stdout.write(self.style.WARNING('\nDRY RUN — rolling back all changes'))
                    raise _DryRunRollback()

            self.stdout.write(self.style.SUCCESS(f'\nRolled over to {new_year_name}'))

        except _DryRunRollback:
            pass

    def _rollover(self, new_year_name, school):
        summary = []

        # Years are per-school again, so a rollover is wholly per-school: each
        # run creates that school's own new year and archives that school's own
        # current one. Two schools means two independent rollovers, which is
        # the point — they can now happen on different days.
        #
        # `AcademicYear.objects` is scoped, and the caller has entered
        # `school_scope(school)`, so this can only see and create rows here.
        current_year = AcademicYear.objects.filter(is_active=True).first()
        if not current_year:
            self.stderr.write(
                self.style.ERROR(f'No active academic year for {school.slug}.')
            )
            return []

        # `is_active` is deliberately NOT in defaults: the partial unique index
        # `academicyear_one_active_per_school` allows exactly one active row
        # per school, so the new year is created dormant and activated below,
        # after the current one has been stood down. Creating it active first
        # would violate the constraint inside this transaction.
        new_year, created = AcademicYear.objects.get_or_create(
            year=new_year_name,
            school=school,
            defaults={'is_active': False, 'archived': False},
        )
        if created:
            current_year.is_active = False
            current_year.archived = True
            current_year.save(update_fields=['is_active', 'archived'])
            new_year.is_active = True
            new_year.save(update_fields=['is_active'])
            summary.append(f'Archived {current_year.year}, created {new_year_name}')
        else:
            summary.append(
                f'Academic year {new_year_name} already exists for '
                f'{school.slug} — rolling its class groups over into it'
            )

        # Only major class groups are promoted — minor groups are re-formed each year.
        old_class_groups = ClassGroup.objects.filter(
            academic_year=current_year,
            category=ClassGroup.MAJOR_CHOICE,
        ).select_related('grade_level')

        group_mapping = {}
        for old_cg in old_class_groups:
            if not old_cg.grade_level:
                continue

            next_grade_number = old_cg.grade_level.number + 1
            next_grade, _ = GradeLevel.objects.get_or_create(number=next_grade_number)

            # `school` stays explicit even though the year now carries one
            # again: ClassGroup declares no SCHOOL_DERIVED_FROM, its column is
            # NOT NULL, and a year belongs to one school anyway — so passing it
            # is both required and a second assertion that this is the right
            # tenant.
            new_cg, _ = ClassGroup.objects.get_or_create(
                academic_year=new_year,
                grade_level=next_grade,
                letter=old_cg.letter,
                category=ClassGroup.MAJOR_CHOICE,
                school=school,
            )
            group_mapping[old_cg.id] = new_cg

        summary.append(f'Created {len(group_mapping)} class groups for {new_year_name}')

        closed_minor = Enrollment.objects.filter(
            class_group__academic_year=current_year,
            class_group__category=ClassGroup.MINOR_CHOICE,
            status='active',
        ).update(status='transferred', end_date=timezone.now().date())
        if closed_minor:
            summary.append(f'Closed {closed_minor} minor group enrollments')

        active_enrollments = Enrollment.objects.filter(
            class_group__academic_year=current_year,
            class_group__category=ClassGroup.MAJOR_CHOICE,
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
                status='active',
            )
            promoted += 1

        summary.append(f'Promoted {promoted} students, graduated {graduated}')
        summary.append('Subject offerings left empty — reassign teachers manually')

        return summary


class _DryRunRollback(Exception):
    pass
