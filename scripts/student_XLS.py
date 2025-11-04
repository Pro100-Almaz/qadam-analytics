import os
import sys
import django
from decouple import config
from google.oauth2.service_account import Credentials
import gspread
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db.models import signals
from get_admin import get_admin_id
from prefill_tables import prefill_school_groups
from apps.authentication import models as auth_models
from apps.authentication.models import CustomUser, Student
from apps.home.models import Subject, ClassRoom, AcademicYear

from datetime import datetime, date
from dateutil import parser

import logging
logging.basicConfig(level=logging.DEBUG, filename="student_logging.log", filemode="w",
                    format='%(asctime)s - %(levelname)s - %(message)s')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

SERVICE_ACCOUNT_FILE = config('SERVICE_ACCOUNT_FILE')
CREDENTIALS_PATH = os.path.join(BASE_DIR, SERVICE_ACCOUNT_FILE)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

credentials = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
client = gspread.authorize(credentials)

SPREADSHEET_URL = config('SPREADSHEET_URL')

def get_sheets_data():
    sheet = client.open_by_url(SPREADSHEET_URL)
    all_sheets = {}
    for worksheet in sheet.worksheets():
        records = worksheet.get_all_records()
        all_sheets[worksheet.title] = records
    return all_sheets

dfs = get_sheets_data()

admin_id = 0

def main():
    prefill_school_groups()
    global admin_id
    admin_id = get_admin_id()

if __name__ == "__main__":
    main()

signals.post_save.disconnect(auth_models.registration_email_post_send, sender=CustomUser)

for sheet_name, rows in dfs.items():
    for idx, row in enumerate(rows):
        try:
            with transaction.atomic():
                date_of_birth = row['Date of Birth']

                try:
                    if not date_of_birth or str(date_of_birth) in ["", 'nan', 'NaT', "None"]:  # is not available
                        raise ValueError(f"Date of Birth is invalid. {date_of_birth} in sheet {sheet_name} at row {idx + 2}")
                    else:
                        if isinstance(date_of_birth, str):
                            cleaned = date_of_birth.strip().replace("ж", "").replace(",", ".")
                            try:
                                date_of_birth = datetime.strptime(cleaned, "%d.%m.%Y").date()
                            except ValueError:
                                date_of_birth = parser.parse(cleaned, dayfirst=True).date()

                        elif isinstance(date_of_birth, (datetime, date)):
                            date_of_birth = date_of_birth if isinstance(date_of_birth, date) else date_of_birth.date()

                        else:
                            raise ValueError(f"Unsupported date format: {date_of_birth}")

                except ValueError as e:
                    logging.error(f"Date of Birth is invalid. {date_of_birth} in sheet {sheet_name} at row {idx + 2}")
                    print(e)

                try:
                    user = CustomUser.objects.update_or_create(
                        username=row['Nickname'],
                        defaults=dict(
                            first_name=row['First Name'],
                            last_name=row['Last Name'],
                            email=row['Email'],
                            role=row['Role'],
                            school=row['School'],
                            address=row['Address'],
                            phone_number=row['Phone (parent)'],
                            date_of_birth=date_of_birth,
                        )
                    )[0]
                    password = str(row.get('Password', '')).strip()
                    if not password:
                        raise ValueError(f"Password is not provided for {row['Nickname']} (sheet: {sheet_name}, row {idx + 2})")

                    user.set_password(str(row['Password']))
                    user.save()
                except (IntegrityError, ValueError, ValidationError) as e:
                    logging.error(e)
                    print(e)
                    continue

                try:
                    year = str(row['Academic Year']).strip()
                    if (len(year) == 9) and ('/' in year):
                        academic_year = AcademicYear.objects.update_or_create(year=row['Academic Year'])[0]
                    else:
                        raise ValueError(f"Academic Year is not provided in expected format for '{row['Academic Year']}'")
                except ValueError as e:
                    logging.error(f"Academic Year is not provided in expected format for '{row['Academic Year']}'. "
                                  f"expected format: yyyy/yyyy")
                    print(e)


                class_room = ClassRoom.objects.update_or_create(
                    name=row['Class'],
                    capacity=26,
                    academic_year=academic_year
                )[0]


                school_group_map = {
                    'Ақ': 1,
                    'Ұлы': 2,
                    'Көк': 3,
                    'Алтын': 4,
                }
                school_group_value = row['School Group (Orda)']

                if school_group_value not in school_group_map:
                    print(
                        f"Invalid school group '{school_group_value}' in sheet {sheet_name}, row {idx + 2}. "
                        f"Expected one of: {list(school_group_map.keys())}"
                    )
                    continue
                school_group_id = school_group_map[school_group_value]


                student = Student.objects.update_or_create(
                    user=user,
                    defaults=dict(
                        academic_year=academic_year,
                        classroom=class_room,
                        school_group_id=school_group_id
                    )
                )[0]

                subject = Subject.objects.update_or_create(
                    name=row['Subjects'],
                    academic_year=academic_year,
                    defaults={
                        "language_group": "KAZ",
                        "status": "active",
                        "progress": 0,
                        "average_points": 0,
                        "maximum_points": 100,
                        "added_by_id": admin_id,
                    }
                )[0]

                student.subjects.add(subject)
                student.save()
        except Exception as e:
            msg = f" ----- Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
            print(msg)
            logging.error(msg)
            continue

