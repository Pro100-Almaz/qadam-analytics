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
                'Slug of the school whose class groups and enrollments to roll '
                'over. Required, not inferred: the academic year itself is '
                'shared (§1a) and is created once, but class groups and '
                'enrollments are per-school, so this has to run once per school.'
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

        # AcademicYear is shared (§1a), so there is no `school=` here and the
        # year half of a rollover happens once no matter how many schools run
        # it. Running this a second time for another school finds the year
        # already created and only does that school's class groups.
        current_year = AcademicYear.objects.filter(is_active=True).first()
        if not current_year:
            self.stderr.write(self.style.ERROR('No active academic year.'))
            return []

        new_year, created = AcademicYear.objects.get_or_create(
            year=new_year_name,
            defaults={'is_active': True, 'archived': False},
        )
        if created:
            current_year.is_active = False
            current_year.archived = True
            current_year.save(update_fields=['is_active', 'archived'])
            summary.append(f'Archived {current_year.year}, created {new_year_name}')
        else:
            summary.append(
                f'Academic year {new_year_name} already exists (shared) — '
                f'rolling over {school.slug} into it'
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

            # `school` is both the tenant key and part of the lookup: the
            # column is NOT NULL and ClassGroup can no longer derive it (§1a
            # removed the year it used to derive from), and without it in the
            # lookup get_or_create would match another school's 7A.
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
