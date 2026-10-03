"""Create parent accounts from the parents survey workbook.

Only two columns are read: ``ФИО родителя`` (full name) and ``Почта``
(email). Everything else in the sheet is ignored — children are bound to the
accounts by hand afterwards.

For every row:

* the full name is ``Surname First [Patronymic]``; the patronymic, when
  present, is dropped because there is no field for it;
* Cyrillic (Russian and Kazakh) is transliterated to Latin and every name is
  re-cased as ``Capitalized`` — some rows are typed in all caps;
* the email, trimmed and lower-cased, becomes both the username and the email;
* a ``CustomUser`` in the ``Parent`` group with a ``Parent`` profile is
  created, with the password ``Qadam2026*`` (parents change it later).

Duplicates are never created. A row whose email already belongs to a user
(matched case-insensitively on email or username, across all schools) is
skipped and reported, and so is a repeat of an email seen earlier in the file.

The script is **dry-run by default** — it does all the work, prints what it
would do and rolls the transaction back. Pass ``--apply`` to commit.

Usage::

    python scripts/student_copying/parents/import_parents_xlsx.py --school <slug>            # dry run
    python scripts/student_copying/parents/import_parents_xlsx.py --school <slug> --dry-run  # same
    python scripts/student_copying/parents/import_parents_xlsx.py --school <slug> --apply
"""

import argparse
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.core.validators import validate_email  # noqa: E402
from django.db import transaction  # noqa: E402
from django.db.models import Q, signals  # noqa: E402

from apps.authentication import models as auth_models  # noqa: E402
from apps.authentication.models import CustomUser, Parent  # noqa: E402
from core.tenancy import school_scope  # noqa: E402
from scripts.student_copying.import_students_xlsx import read_workbook  # noqa: E402
from scripts.utils.bootstrap import add_school_argument, resolve_school  # noqa: E402
from scripts.utils.logging_config import logger  # noqa: E402

DEFAULT_WORKBOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parents.xlsx')

DEFAULT_PASSWORD = 'Parent2026!'

NAME_HEADER = 'фио родителя'
EMAIL_HEADER = 'почта'

# ---------------------------------------------------------------------------
# Transliteration
# ---------------------------------------------------------------------------

# Russian + Kazakh Cyrillic -> Latin, close to the spelling used in Kazakh
# passports. `е` is handled separately (see transliterate()).
CYRILLIC_TO_LATIN = {
    'а': 'a', 'ә': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'ғ': 'g', 'д': 'd',
    'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'i', 'і': 'i', 'к': 'k',
    'қ': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'ң': 'n', 'о': 'o', 'ө': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ұ': 'u', 'ү': 'u',
    'ф': 'f', 'х': 'kh', 'һ': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh',
    'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

VOWELS = set('аәеёиіоөуұүыэюяaeiouy')


def transliterate(text):
    """Cyrillic (incl. Kazakh letters) -> lower-case Latin. Latin passes through.

    `е` becomes `ye` at the start of a word and after a vowel or a hard/soft
    sign (Ерханов -> yerkhanov, Назарбаева -> nazarbayeva), `e` elsewhere.
    """
    result = []
    previous = ''
    for char in text.lower():
        if char == 'е':
            result.append('ye' if not previous.isalpha() or previous in VOWELS or previous in 'ъь' else 'e')
        else:
            result.append(CYRILLIC_TO_LATIN.get(char, char))
        previous = char
    return ''.join(result)


def capitalize_name(name):
    """'ZHANAR' / 'zhanar' -> 'Zhanar'; hyphenated parts are capitalized each."""
    return '-'.join(part.capitalize() for part in name.split('-'))


def parse_full_name(full_name):
    """'Сарина Асель Науановна' -> ('Sarina', 'Asel'): (last_name, first_name).

    The patronymic, if any, is dropped. A single word is taken as the first
    name, with an empty surname.
    """
    words = full_name.split()
    if not words:
        raise ValueError('empty name')
    words = [capitalize_name(transliterate(word)) for word in words]
    if len(words) == 1:
        return '', words[0]
    return words[0], words[1]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def find_columns(header_row):
    columns = {}
    for index, title in enumerate(header_row):
        title = str(title).strip().lower()
        if title == NAME_HEADER:
            columns['name'] = index
        elif title == EMAIL_HEADER:
            columns['email'] = index
    missing = {'name', 'email'} - set(columns)
    if missing:
        raise SystemExit(
            f'header row is missing {sorted(missing)} — expected '
            f'"{NAME_HEADER}" and "{EMAIL_HEADER}", got {header_row}')
    return columns


def value_at(row, index):
    return str(row[index]).strip() if index < len(row) else ''


def import_parents(path, school, report):
    parent_group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_PARENT)
    seen_emails = {}

    for sheet_name, rows in read_workbook(path):
        if not rows:
            continue
        columns = find_columns(rows[0])
        print(f'\n== {sheet_name} ({len(rows) - 1} rows)')

        for row_number, row in enumerate(rows[1:], start=2):
            raw_name = value_at(row, columns['name'])
            email = value_at(row, columns['email']).lower()
            if not raw_name and not email:
                continue
            report['rows'] += 1
            where = f'row {row_number}'

            try:
                if not email:
                    raise ValueError(f'"{raw_name}": no email')
                try:
                    validate_email(email)
                except ValidationError:
                    raise ValueError(f'"{raw_name}": invalid email {email!r}')
                last_name, first_name = parse_full_name(raw_name)
            except ValueError as exc:
                message = f'{where}: {exc}'
                print(f'   SKIP {message}')
                report['skipped'].append(message)
                continue

            if email in seen_emails:
                report['duplicates_in_file'].append(
                    f'{where}: {email} ("{raw_name}") — same as {seen_emails[email]}')
                continue
            seen_emails[email] = f'row {row_number}'

            existing = CustomUser.objects.filter(
                Q(email__iexact=email) | Q(username__iexact=email)).first()
            if existing is not None:
                roles = ', '.join(existing.groups.values_list('name', flat=True)) or 'no role'
                report['already_exist'].append(
                    f'{where}: {email} -> existing user "{existing.username}" '
                    f'({existing.get_full_name() or "no name"}; {roles})')
                continue

            if not last_name:
                report['warnings'].append(f'{where}: "{raw_name}" has no surname — created with first name only')

            try:
                with transaction.atomic():
                    user = CustomUser(
                        username=email,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        school=school,
                    )
                    user.set_password(DEFAULT_PASSWORD)
                    user.save()
                    user.groups.add(parent_group)
                    Parent.objects.create(user=user)
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the import
                message = f'{where}: {email}: {exc}'
                print(f'   SKIP {message}')
                logger.error(message)
                report['skipped'].append(message)
                continue

            report['created'] += 1
            full_name = f'{last_name} {first_name}'.strip()
            print(f'   + {full_name}  <{email}>   (from "{raw_name}")')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--file', default=DEFAULT_WORKBOOK, help='path to the .xlsx workbook')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='show what would be done and roll back (default)')
    mode.add_argument('--apply', action='store_true', help='write to the database')
    add_school_argument(parser)
    args = parser.parse_args()

    if not os.path.exists(args.file):
        parser.error(f'workbook not found: {args.file}')
    school = resolve_school(args.school)

    # New parents must not get the registration e-mail until the accounts are reviewed.
    signals.post_save.disconnect(auth_models.registration_email_post_send, sender=CustomUser)

    print(f'Workbook : {args.file}')
    print(f'School   : {school.slug}')
    print(f'Mode     : {"APPLY (writing to the database)" if args.apply else "DRY RUN (nothing is saved)"}')

    report = {
        'rows': 0,
        'created': 0,
        'already_exist': [],
        'duplicates_in_file': [],
        'warnings': [],
        'skipped': [],
    }

    class Rollback(Exception):
        pass

    try:
        with school_scope(school), transaction.atomic():
            import_parents(args.file, school, report)
            if not args.apply:
                raise Rollback
    except Rollback:
        pass

    print('\n' + '-' * 60)
    print(f'rows read            : {report["rows"]}')
    print(f'parents created      : {report["created"]} (password "{DEFAULT_PASSWORD}")')
    for key, title in (
        ('already_exist', 'skipped, email already registered'),
        ('duplicates_in_file', 'skipped, email repeated in the file'),
        ('warnings', 'warnings'),
        ('skipped', 'skipped, invalid row'),
    ):
        if report[key]:
            print(f'{title} ({len(report[key])}):')
            for entry in report[key]:
                print(f'   - {entry}')

    if not args.apply:
        print('\nDRY RUN — nothing was written. Re-run with --apply to commit.')


if __name__ == '__main__':
    main()
