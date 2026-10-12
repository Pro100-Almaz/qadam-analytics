"""Create parent accounts from the class e-mail lists workbook (parents_v2.xlsx).

The workbook has a summary sheet (``Барлығы``) plus one sheet per class. Each
sheet starts with a few title rows; the header row is found by looking for the
``Анасының аты-жөні`` (mother's full name) and ``E-mail`` columns, and data
starts on the row after it. Every sheet is read, because the class sheets
carry a few rows the summary lacks — repeats are merged by e-mail.

Only the mother gets an account: the sheet has a single e-mail column and it
is always assigned to her. The father's column and the student's name are
ignored — children are bound to the accounts by hand afterwards.

For every row:

* the mother's full name is ``Surname First [Patronymic]``; the patronymic is
  dropped because there is no field for it;
* Cyrillic (Russian and Kazakh) is transliterated to Latin and re-cased as
  ``Capitalized``;
* the e-mail, trimmed and lower-cased, becomes both the username and the
  e-mail. A cell holding two addresses (``a@x / b@y``) uses the first and
  reports the second;
* a ``CustomUser`` in the ``Parent`` group with a ``Parent`` profile is
  created, with the default password (parents change it later).

Duplicates are never created. A row whose e-mail already belongs to a user
(matched case-insensitively on e-mail or username, across all schools) is
skipped and reported, and so is a repeat of an e-mail seen earlier in the file.

The script is **dry-run by default** — it does all the work, prints what it
would do and rolls the transaction back. Pass ``--apply`` to commit.

Usage::

    python scripts/student_copying/parents/import_parents_xlsx_v2.py --school <slug>            # dry run
    python scripts/student_copying/parents/import_parents_xlsx_v2.py --school <slug> --dry-run  # same
    python scripts/student_copying/parents/import_parents_xlsx_v2.py --school <slug> --apply
"""

import argparse
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django  # noqa: E402
import openpyxl  # noqa: E402

django.setup()

from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.core.validators import validate_email  # noqa: E402
from django.db import transaction  # noqa: E402
from django.db.models import Q, signals  # noqa: E402

from apps.authentication import models as auth_models  # noqa: E402
from apps.authentication.models import CustomUser, Parent  # noqa: E402
from core.tenancy import school_scope  # noqa: E402
from scripts.student_copying.parents.import_parents_xlsx import (  # noqa: E402
    DEFAULT_PASSWORD, parse_full_name)
from scripts.utils.bootstrap import add_school_argument, resolve_school  # noqa: E402
from scripts.utils.logging_config import logger  # noqa: E402

DEFAULT_WORKBOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parents_v2.xlsx')

NAME_HEADER = 'анасының аты-жөні'
EMAIL_HEADER = 'e-mail'

# How far down a sheet to look for the header row.
HEADER_SEARCH_ROWS = 20

EMAIL_SEPARATORS = re.compile(r'\s*[/,;]\s*')
# 'АсельРуслановна' -> 'Асель Руслановна': a missing space between two words.
GLUED_WORDS = re.compile(r'(?<=[a-zа-яәғқңөұүһі])(?=[A-ZА-ЯӘҒҚҢӨҰҮҺІЁ])')


def read_workbook(path):
    """Return ``[(sheet_name, [(row_number, [cell, ...]), ...]), ...]``.

    Row numbers are the ones Excel shows, blank rows included, so the report
    points at the right line.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [
            (sheet.title, [
                (row_number, ['' if cell is None else str(cell).strip() for cell in row])
                for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1)
            ])
            for sheet in workbook.worksheets
        ]
    finally:
        workbook.close()


def find_header(rows):
    """Return ``(position in rows, {'name': col, 'email': col})`` or ``(None, None)``."""
    for position, (_, row) in enumerate(rows[:HEADER_SEARCH_ROWS]):
        titles = [title.lower() for title in row]
        if NAME_HEADER in titles and EMAIL_HEADER in titles:
            return position, {'name': titles.index(NAME_HEADER), 'email': titles.index(EMAIL_HEADER)}
    return None, None


def value_at(row, index):
    return row[index] if index < len(row) else ''


def split_emails(cell):
    return [email.lower() for email in EMAIL_SEPARATORS.split(cell.strip()) if email]


def import_parents(path, school, report):
    parent_group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_PARENT)
    seen_emails = {}  # email -> (where, raw_name)
    emails_by_name = {}  # transliterated full name -> {email, ...}
    seen_problems = set()  # the same bad row is repeated on the summary and class sheets

    for sheet_name, rows in read_workbook(path):
        header_position, columns = find_header(rows)
        if header_position is None:
            print(f'\n== {sheet_name}: no "{NAME_HEADER}" / "{EMAIL_HEADER}" header, sheet skipped')
            continue
        header_row_number = rows[header_position][0]
        print(f'\n== {sheet_name} (header on row {header_row_number}, data from row {header_row_number + 1})')

        for row_number, row in rows[header_position + 1:]:
            raw_name = ' '.join(value_at(row, columns['name']).split())
            emails = split_emails(value_at(row, columns['email']))
            if not raw_name and not emails:
                continue
            report['rows'] += 1
            where = f'{sheet_name} row {row_number}'

            try:
                if not raw_name:
                    raise ValueError(f'{emails[0]}: no mother name')
                if not emails:
                    raise ValueError(f'"{raw_name}": no email')
                email = emails[0]
                try:
                    # Non-ASCII slips past validate_email (IDN), e.g. a Cyrillic 'с' in '.сom'.
                    if not email.isascii():
                        raise ValidationError('non-ASCII')
                    validate_email(email)
                except ValidationError:
                    raise ValueError(f'"{raw_name}": invalid email {email!r}')
                last_name, first_name = parse_full_name(GLUED_WORDS.sub(' ', raw_name))
            except ValueError as exc:
                if str(exc) in seen_problems:
                    report['repeats'] += 1
                    continue
                seen_problems.add(str(exc))
                message = f'{where}: {exc}'
                print(f'   SKIP {message}')
                report['skipped'].append(message)
                continue

            if email in seen_emails:
                first_where, first_name_seen = seen_emails[email]
                if first_name_seen.lower() == raw_name.lower():
                    report['repeats'] += 1
                else:
                    report['email_conflicts'].append(
                        f'{where}: {email} given for "{raw_name}", but {first_where} gave it to "{first_name_seen}"')
                continue
            seen_emails[email] = (where, raw_name)

            if len(emails) > 1:
                report['warnings'].append(
                    f'{where}: "{raw_name}" has several emails — using {email}, ignoring {", ".join(emails[1:])}')

            full_name = f'{last_name} {first_name}'.strip()
            emails_by_name.setdefault(full_name, set()).add(email)

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
            print(f'   + {full_name}  <{email}>   (from "{raw_name}")')

    for full_name, emails in sorted(emails_by_name.items()):
        if len(emails) > 1:
            report['warnings'].append(
                f'"{full_name}" appears with {len(emails)} emails ({", ".join(sorted(emails))}) '
                f'— one account per email, check whether it is the same person')


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
        'repeats': 0,
        'already_exist': [],
        'email_conflicts': [],
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
    print(f'repeated rows merged : {report["repeats"]} (the same row again on another sheet)')
    for key, title in (
        ('already_exist', 'skipped, email already registered'),
        ('email_conflicts', 'skipped, email already used in the file for another name'),
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
