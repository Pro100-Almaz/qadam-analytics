"""Import / refresh students from the "Stud info" workbook.

The workbook holds one sheet per class group. Every sheet has the columns
``First Name``, ``Last Name``, ``Email``, ``Password`` and (usually) ``Class``.
When the ``Class`` column is missing or empty, the sheet name is used as the
class group name instead.

Matching is done on **first name + last name** (case-insensitive):

* the student already exists  -> email, password and class group are updated;
* the student does not exist  -> ``CustomUser`` + ``Student`` are created,
  the user is put into the ``Student`` group and enrolled;
* the class group (grade number + letter, e.g. ``8MA``) does not exist for the
  target academic year -> it is created, together with its ``GradeLevel``.

An empty password cell means: a new user gets the default ``Qadam2026*``, an
existing user keeps the password they already have.

The script is **dry-run by default** — it prints exactly what it would do and
rolls everything back. Pass ``--apply`` to actually write to the database.

Usage::

    python scripts/student_copying/import_students_xlsx.py                # dry run
    python scripts/student_copying/import_students_xlsx.py --apply
    python scripts/student_copying/import_students_xlsx.py --apply --year 2026/2027
    python scripts/student_copying/import_students_xlsx.py --sheets 1AS,5 --apply

The .xlsx is parsed with the standard library (zipfile + ElementTree), so no
extra dependency such as openpyxl is required.
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import Group  # noqa: E402
from django.db import transaction  # noqa: E402
from django.db.models import signals  # noqa: E402

from apps.authentication import models as auth_models  # noqa: E402
from apps.authentication.models import CustomUser, Student  # noqa: E402
from apps.home.models import AcademicYear, ClassGroup, Enrollment, GradeLevel  # noqa: E402
from scripts.utils.logging_config import logger  # noqa: E402

DEFAULT_WORKBOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Stud info 2026_2027.xlsx')

# Password given to a newly created student when the workbook leaves the cell empty.
DEFAULT_PASSWORD = 'Qadam2026*'

# Class names that cannot be parsed automatically (or that should land in a
# specific group) can be remapped here, e.g. {'5': '5A'}.
CLASS_NAME_OVERRIDES = {}

# ---------------------------------------------------------------------------
# Minimal .xlsx reader (no third-party dependencies)
# ---------------------------------------------------------------------------

MAIN_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
DOC_REL_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _column_index(cell_ref):
    """'C7' -> 2 (zero-based column index)."""
    letters = ''.join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - ord('A') + 1)
    return index - 1


def _read_shared_strings(archive):
    try:
        raw = archive.read('xl/sharedStrings.xml')
    except KeyError:
        return []
    return [
        ''.join(node.text or '' for node in item.iter(MAIN_NS + 't'))
        for item in ET.fromstring(raw)
    ]


def _read_sheet_rows(archive, sheet_path, shared_strings):
    """Yield each row of a worksheet as a list of strings."""
    root = ET.fromstring(archive.read(sheet_path))
    rows = []
    for row in root.iter(MAIN_NS + 'row'):
        cells = {}
        for cell in row.iter(MAIN_NS + 'c'):
            cell_type = cell.get('t')
            if cell_type == 'inlineStr':
                value = ''.join(node.text or '' for node in cell.iter(MAIN_NS + 't'))
            else:
                value_node = cell.find(MAIN_NS + 'v')
                if value_node is None or value_node.text is None:
                    continue
                if cell_type == 's':
                    value = shared_strings[int(value_node.text)]
                else:
                    value = value_node.text
            value = (value or '').strip()
            if value:
                cells[_column_index(cell.get('r'))] = value
        if not cells:
            rows.append([])
            continue
        width = max(cells) + 1
        rows.append([cells.get(i, '') for i in range(width)])
    return rows


def read_workbook(path):
    """Return ``[(sheet_name, [row, ...]), ...]`` for a .xlsx file."""
    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)

        relations = {
            rel.get('Id'): rel.get('Target')
            for rel in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        }

        sheets = []
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        for sheet in workbook.find(MAIN_NS + 'sheets'):
            target = relations[sheet.get(DOC_REL_NS + 'id')].lstrip('/')
            if not target.startswith('xl/'):
                target = 'xl/' + target
            sheets.append((sheet.get('name'), _read_sheet_rows(archive, target, shared_strings)))
        return sheets


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------

HEADER_ALIASES = {
    'first name': 'first_name',
    'firstname': 'first_name',
    'name': 'first_name',
    'last name': 'last_name',
    'lastname': 'last_name',
    'surname': 'last_name',
    'email': 'email',
    'e-mail': 'email',
    'mail': 'email',
    'password': 'password',
    'pass': 'password',
    'class': 'class_name',
    'class group': 'class_name',
    'classgroup': 'class_name',
    'group': 'class_name',
}

REQUIRED_COLUMNS = ('first_name', 'last_name')


def map_header(header_row):
    """Map a header row to ``{field_name: column_index}``."""
    mapping = {}
    for index, title in enumerate(header_row):
        field = HEADER_ALIASES.get(str(title).strip().lower())
        if field and field not in mapping:
            mapping[field] = index
    return mapping


def cell(row, mapping, field):
    index = mapping.get(field)
    if index is None or index >= len(row):
        return ''
    return str(row[index]).strip()


CLASS_RE = re.compile(r'^(\d{1,2})\s*[-_\s]?\s*(.*)$')


def parse_class_name(raw_name):
    """'8MA' -> (8, 'MA'); '5.0' -> (5, ''); '7 Б' -> (7, 'Б')."""
    text = str(raw_name).strip()
    text = CLASS_NAME_OVERRIDES.get(text, text)
    # Excel keeps a purely numeric class ("5") as a float ("5.0").
    if re.fullmatch(r'\d+\.0+', text):
        text = text.split('.')[0]
    match = CLASS_RE.match(text)
    if not match:
        raise ValueError(f"cannot parse class name {raw_name!r} (expected grade number + letter, e.g. '8MA')")
    grade = int(match.group(1))
    letter = match.group(2).strip()
    return grade, letter


def class_label(grade, letter):
    return f'{grade}{letter}' if letter else str(grade)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_academic_year(year_value):
    academic_year = AcademicYear.objects.filter(year=year_value).first()
    if academic_year:
        return academic_year, False
    return AcademicYear.objects.create(year=year_value, is_active=False, archived=False), True


def get_or_create_class_group(academic_year, grade, letter, cache, report):
    key = (grade, letter.lower())
    if key in cache:
        return cache[key]

    grade_level = GradeLevel.objects.filter(number=grade).first()
    if grade_level is None:
        grade_level = GradeLevel.objects.create(number=grade)
        report['grade_levels_created'].append(grade)

    class_group = ClassGroup.objects.filter(
        academic_year=academic_year,
        grade_level=grade_level,
        letter__iexact=letter,
    ).first()
    if class_group is None:
        class_group = ClassGroup.objects.create(
            academic_year=academic_year,
            grade_level=grade_level,
            letter=letter,
        )
        report['class_groups_created'].append(class_label(grade, letter))

    cache[key] = class_group
    return class_group


def find_user(first_name, last_name):
    """Look a user up by first + last name. Raises on an ambiguous match."""
    matches = list(
        CustomUser.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name,
        )[:5]
    )
    if len(matches) > 1:
        usernames = ', '.join(u.username for u in matches)
        raise ValueError(f'{len(matches)} users match "{first_name} {last_name}" ({usernames}) — skipped')
    return matches[0] if matches else None


def build_username(first_name, last_name):
    """Follow the repo convention ``first.last``, suffixed on collision."""
    base = re.sub(r'[^a-z0-9._-]', '', f'{first_name}.{last_name}'.lower().replace(' ', '.'))
    base = re.sub(r'\.+', '.', base).strip('.') or 'student'
    username = base
    counter = 2
    while CustomUser.objects.filter(username=username).exists():
        username = f'{base}.{counter}'
        counter += 1
    return username


def sync_enrollment(student, class_group, academic_year):
    """Return 'unchanged' | 'moved' | 'enrolled'."""
    active = Enrollment.objects.filter(
        student=student,
        academic_year=academic_year,
        status='active',
    ).select_related('class_group').first()

    if active and active.class_group_id == class_group.id:
        return 'unchanged'

    Enrollment.enroll_student(student, class_group, academic_year)
    return 'moved' if active else 'enrolled'


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def process_row(row, mapping, sheet_name, academic_year, student_group, class_cache, report):
    first_name = cell(row, mapping, 'first_name')
    last_name = cell(row, mapping, 'last_name')
    email = cell(row, mapping, 'email')
    password = cell(row, mapping, 'password')
    raw_class = cell(row, mapping, 'class_name') or sheet_name

    if not first_name or not last_name:
        raise ValueError('missing first name or last name')

    grade, letter = parse_class_name(raw_class)
    class_group = get_or_create_class_group(academic_year, grade, letter, class_cache, report)

    user = find_user(first_name, last_name)
    changes = []

    if user is None:
        user = CustomUser(
            username=build_username(first_name, last_name),
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        user.set_password(password or DEFAULT_PASSWORD)
        user.save()
        changes.append(f'created user "{user.username}"')
        if not password:
            changes.append(f'no password in the sheet, used the default "{DEFAULT_PASSWORD}"')
            report['default_passwords'].append(f'{user.username} ({sheet_name})')
        report['users_created'] += 1
    else:
        if email and user.email != email:
            changes.append(f'email {user.email or "-"} -> {email}')
            user.email = email
        if password:
            user.set_password(password)
            changes.append('password reset')
        else:
            # An existing account keeps its current password — replacing it with
            # the shared default would be a downgrade.
            report['password_kept'].append(f'{user.username} ({sheet_name})')
        if changes:
            user.save()
        report['users_updated'] += 1

    if not user.groups.filter(name=CustomUser.GROUP_STUDENT).exists():
        user.groups.add(student_group)
        changes.append('added to Student group')

    student = Student.objects.filter(user=user).first()
    if student is None:
        student = Student.objects.create(user=user, academic_year=academic_year)
        changes.append('created student profile')
        report['profiles_created'] += 1
    elif student.academic_year_id != academic_year.id:
        student.academic_year = academic_year
        student.save(update_fields=['academic_year'])
        changes.append(f'academic year -> {academic_year.year}')

    enrollment_state = sync_enrollment(student, class_group, academic_year)
    if enrollment_state == 'enrolled':
        changes.append(f'enrolled into {class_label(grade, letter)}')
        report['enrolled'] += 1
    elif enrollment_state == 'moved':
        changes.append(f'moved to {class_label(grade, letter)}')
        report['moved'] += 1

    return user, changes


def import_workbook(path, academic_year, only_sheets, verbose):
    report = {
        'users_created': 0,
        'users_updated': 0,
        'profiles_created': 0,
        'enrolled': 0,
        'moved': 0,
        'rows': 0,
        'skipped': [],
        'class_groups_created': [],
        'grade_levels_created': [],
        'default_passwords': [],
        'password_kept': [],
    }
    seen_names = defaultdict(list)
    class_cache = {}
    student_group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_STUDENT)

    for sheet_name, rows in read_workbook(path):
        if only_sheets and sheet_name not in only_sheets:
            continue

        non_empty = [row for row in rows if any(str(value).strip() for value in row)]
        if not non_empty:
            print(f'\n== {sheet_name}: empty sheet, skipped')
            continue

        mapping = map_header(non_empty[0])
        missing = [field for field in REQUIRED_COLUMNS if field not in mapping]
        if missing:
            message = f'sheet "{sheet_name}": header is missing {missing} — whole sheet skipped'
            print(f'\n== {message}')
            logger.error(message)
            report['skipped'].append(message)
            continue

        print(f'\n== {sheet_name} ({len(non_empty) - 1} rows)')
        for offset, row in enumerate(non_empty[1:], start=2):
            report['rows'] += 1
            first_name = cell(row, mapping, 'first_name')
            last_name = cell(row, mapping, 'last_name')
            key = (first_name.lower(), last_name.lower())
            if key in seen_names:
                print(f'   ! row {offset}: "{first_name} {last_name}" already seen in {seen_names[key][0]} '
                      f'— processed again, last row wins')
            seen_names[key].append(f'{sheet_name} row {offset}')

            try:
                with transaction.atomic():
                    user, changes = process_row(
                        row, mapping, sheet_name, academic_year, student_group, class_cache, report,
                    )
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the import
                message = f'sheet "{sheet_name}", row {offset}: {exc}'
                print(f'   SKIP {message}')
                logger.error(message)
                report['skipped'].append(message)
                continue

            if changes:
                print(f'   {first_name} {last_name}: ' + '; '.join(changes))
            elif verbose:
                print(f'   {first_name} {last_name}: up to date')

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--file', default=DEFAULT_WORKBOOK, help='path to the .xlsx workbook')
    parser.add_argument('--year', default='2026/2027', help='academic year the students belong to (default: 2026/2027)')
    parser.add_argument('--sheets', default='', help='comma separated list of sheet names to import (default: all)')
    parser.add_argument('--apply', action='store_true', help='write to the database (otherwise everything is rolled back)')
    parser.add_argument('--verbose', action='store_true', help='also print rows that needed no change')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        parser.error(f'workbook not found: {args.file}')

    only_sheets = {name.strip() for name in args.sheets.split(',') if name.strip()}

    # Newly created users must not trigger the registration e-mail.
    signals.post_save.disconnect(auth_models.registration_email_post_send, sender=CustomUser)

    print(f'Workbook      : {args.file}')
    print(f'Academic year : {args.year}')
    print(f'Mode          : {"APPLY (writing to the database)" if args.apply else "DRY RUN (nothing is saved)"}')

    class Rollback(Exception):
        pass

    report = None
    try:
        with transaction.atomic():
            academic_year, created = get_academic_year(args.year)
            if created:
                print(f'   + created academic year {academic_year.year}')
            report = import_workbook(args.file, academic_year, only_sheets, args.verbose)
            if not args.apply:
                raise Rollback
    except Rollback:
        pass

    print('\n' + '-' * 60)
    print(f'rows processed        : {report["rows"]}')
    print(f'users created         : {report["users_created"]}')
    print(f'existing users updated: {report["users_updated"]}')
    print(f'student profiles added: {report["profiles_created"]}')
    print(f'new enrollments       : {report["enrolled"]}')
    print(f'class changes         : {report["moved"]}')
    if report['grade_levels_created']:
        print(f'grade levels created  : {sorted(set(report["grade_levels_created"]))}')
    if report['class_groups_created']:
        print(f'class groups created  : {sorted(set(report["class_groups_created"]))}')
    if report['default_passwords']:
        print(f'default password "{DEFAULT_PASSWORD}" used for {len(report["default_passwords"])} new users:')
        for entry in report['default_passwords']:
            print(f'   - {entry}')
    if report['password_kept']:
        print(f'existing password kept (blank cell) for {len(report["password_kept"])} users:')
        for entry in report['password_kept']:
            print(f'   - {entry}')
    if report['skipped']:
        print(f'skipped ({len(report["skipped"])}):')
        for message in report['skipped']:
            print(f'   - {message}')

    if not args.apply:
        print('\nDRY RUN — nothing was written. Re-run with --apply to commit.')


if __name__ == '__main__':
    main()
