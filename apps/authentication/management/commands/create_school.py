"""Stand up a new tenant: school, first Admin, active year, Orda houses.

Onboarding used to be an undocumented sequence of five things done by hand in
`/admin/` and a shell, in an order that matters and with one step —
`scripts/prefill_tables.py` — that had been broken since phase 1 added a NOT
NULL `school_id` its raw INSERT did not supply. Each step is individually
obvious and the whole is easy to half-finish, which on a tenant boundary means
a school that exists but whose users cannot be assigned a year, or whose Orda
houses silently belong to school #1.

So it is one command, and it is idempotent: run it again after fixing whatever
went wrong and it creates only what is missing. `--dry-run` executes the real
code path inside a transaction that is then rolled back, rather than a
parallel "pretend" branch that drifts from the real one — so a constraint that
would fire on the real run fires on the rehearsal too.

    python manage.py create_school \\
        --slug astana_29 --name "Astana School 29" \\
        --admin-email head@astana29.kz --year 2026/2027

What it deliberately does NOT do is seed a `Subject` catalogue. Subjects are
per-school by decision, they carry no natural universal list (three active
"Русский язык" rows exist in school #1, distinguished only by their offerings),
and inventing one would hand the new school a catalogue it then has to prune.
The command says so at the end rather than leaving you to wonder.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.crypto import get_random_string

from apps.authentication.models import CustomUser, School, SchoolGroup
from apps.home.models import AcademicYear
from core.tenancy import school_scope

#: The four Orda houses, as `scripts/prefill_tables.py` seeded them before that
#: script stopped working. Avatars point at objects already in the media
#: bucket: `S3_STORAGE_OPTIONS["location"]` is global, so these files are
#: shared across tenants rather than copied per school. A school that wants its
#: own artwork uploads it over the top in the admin.
ORDA_HOUSES = (
    ('Aq Orda', 'school_group/Aq-orda.jpg'),
    ('Uly Orda', 'school_group/Uly-Orda.png'),
    ('Kok Orda', 'school_group/Kok-Orda.png'),
    ('Altyn Orda', 'school_group/Altyn_Orda.png'),
)


class Command(BaseCommand):
    help = 'Create a school and the minimum it needs to be usable.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug', required=True,
            help=(
                'Stable internal key. This is what every script\'s --school '
                'flag takes and what migrations name a tenant by, so choose it '
                'once: the admin makes it read-only after creation.'
            ),
        )
        parser.add_argument('--name', required=True, help='Display name.')
        parser.add_argument('--short-name', default='')
        parser.add_argument('--address', default='')
        parser.add_argument('--contact-phone', default='')
        parser.add_argument('--contact-email', default='')
        parser.add_argument('--timezone', default='Asia/Almaty')

        parser.add_argument(
            '--admin-email',
            help=(
                'Email of the first Admin. Omit to create no user — but then '
                'nobody can administer the school until you add one.'
            ),
        )
        parser.add_argument(
            '--admin-username',
            help='Defaults to --admin-email.',
        )
        parser.add_argument(
            '--admin-password',
            help=(
                'Omit to generate one and print it once. It is printed rather '
                'than emailed on purpose: email delivery is the step most '
                'likely to be unconfigured on a fresh install, and a command '
                'that reports success while the password went nowhere is how '
                'an account becomes unreachable.'
            ),
        )
        parser.add_argument(
            '--year',
            help=(
                'Academic year to create and activate, e.g. 2026/2027. Since '
                'years went back to being per-school, a tenant without one '
                'cannot enrol a student: assign_academic_year_for_student '
                'reads the active year off the user\'s own school.'
            ),
        )
        parser.add_argument(
            '--no-orda', action='store_true',
            help='Skip the four Orda houses.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Do everything, then roll it back.',
        )

    def handle(self, *args, **options):
        slug = options['slug']
        dry_run = options['dry_run']

        if options['admin_password'] and not options['admin_email']:
            raise CommandError('--admin-password needs --admin-email.')

        generated_password = None
        try:
            with transaction.atomic():
                school, created = School.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'name': options['name'],
                        'short_name': options['short_name'],
                        'address': options['address'],
                        'contact_phone': options['contact_phone'],
                        'contact_email': options['contact_email'],
                        'timezone': options['timezone'],
                    },
                )
                self._report('School', school.name, created, extra=f'#{school.pk}')

                # Everything below is tenant data, so it needs a scope — the
                # managers fail closed without one. This is also what makes the
                # command safe to run on a live install: nothing it creates can
                # land in another school, whatever the ambient environment.
                with school_scope(school):
                    if options['year']:
                        self._create_year(school, options['year'])
                    if not options['no_orda']:
                        self._create_orda_houses(school)
                    if options['admin_email']:
                        generated_password = self._create_admin(school, options)

                if dry_run:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f'Nothing was created: {exc}') from exc

        if generated_password:
            self.stdout.write(self.style.WARNING(
                f'\nGenerated password: {generated_password}\n'
                'Shown once. Change it on first sign-in.'
            ))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\n--dry-run: everything above was rolled back. The ids are '
                'real but no longer exist.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nSchool "{school.name}" is ready.'
            ))
        self.stdout.write(
            'Subject catalogue is empty by design — add subjects in /admin/ '
            'with the school switcher set to this school.'
        )

    # ── the pieces ──────────────────────────────────────────────────────────

    def _create_year(self, school, year):
        """The active year for this school. Quarter dates are set afterwards.

        `is_active=True` is safe on a school that has none: the partial unique
        `academicyear_one_active_per_school` allows exactly one, and a brand new
        tenant has zero. On a re-run the existing row is reused rather than a
        second one activated, which is what that constraint would refuse.
        """
        row, created = AcademicYear.objects.get_or_create(
            school=school, year=year,
            defaults={'is_active': True, 'archived': False},
        )
        self._report('Academic year', row.year, created,
                     extra='active' if row.is_active else 'NOT active')
        if not created and not row.is_active:
            self.stdout.write(self.style.WARNING(
                f'  {row.year} exists but is not active. Activate it in '
                f'/admin/ once the school\'s current year is stood down.'
            ))

    def _create_orda_houses(self, school):
        for name, avatar in ORDA_HOUSES:
            row, created = SchoolGroup.objects.get_or_create(
                school=school, name=name, defaults={'avatar': avatar},
            )
            self._report('Orda house', row.name, created)

    def _create_admin(self, school, options):
        """The first Admin. Returns the generated password, or None.

        `CustomUser.objects` is global by design, so the existence check has to
        be too — a username collides across the whole install, not per tenant,
        and finding out at the INSERT is a confusing way to learn it.
        """
        email = options['admin_email']
        username = options['admin_username'] or email
        existing = CustomUser.objects.filter(username=username).first()
        if existing is not None:
            if existing.school_id != school.pk:
                raise CommandError(
                    f'User "{username}" already exists and belongs to school '
                    f'#{existing.school_id}, not #{school.pk}. Usernames are '
                    f'global; pick another with --admin-username.'
                )
            self._report('Admin', username, created=False)
            return None

        password = options['admin_password']
        generated = None
        if not password:
            password = generated = get_random_string(14)

        user = CustomUser.objects.create_user(
            username=username, email=email, password=password, school=school,
        )
        # The app-level Admin role, not Django staff: `/admin/` is superuser
        # territory (selectable_schools returns nothing for anyone else), so
        # is_staff here would grant a login that shows an empty switcher.
        user.groups.add(Group.objects.get_or_create(name=CustomUser.GROUP_ADMIN)[0])
        self._report('Admin', username, created=True)
        return generated

    def _report(self, kind, name, created, extra=''):
        verb = 'Created' if created else 'Exists '
        style = self.style.SUCCESS if created else self.style.NOTICE
        suffix = f' ({extra})' if extra else ''
        self.stdout.write(style(f'{verb} {kind}: {name}{suffix}'))
