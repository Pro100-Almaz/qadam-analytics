import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from scripts.users.parent_XLS import process_parent
from scripts.users.student_XLS import process_student
from scripts.users.supervisor_XLS import process_supervisor
from scripts.users.teacher_XLS import process_teacher
from scripts.users.get_admin import get_admin_id
from scripts.users.generate_password import generate_password

from scripts.prefill_tables import prefill_school_groups
from scripts.reading_data import get_sheets_data
from scripts.writing_data import get_writable_sheet
from scripts.utils.logging_config import logger

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import signals

from apps.authentication import models as auth_models
from apps.authentication.models import CustomUser

from datetime import datetime, date
from dateutil import parser
import random

dfs = get_sheets_data()

admin_id = 0

def main():
    prefill_school_groups()
    global admin_id
    admin_id = get_admin_id()

if __name__ == "__main__":
    main()

def col_to_letter(col):
    result = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        result = chr(65 + remainder) + result
    return result

signals.post_save.disconnect(auth_models.registration_email_post_send, sender=CustomUser)

for sheet_name, rows in dfs.items():
    check = sheet_name.lower()
    if not ('subject' in check or 'lesson' in check or 'grad' in check or 'stat' in check or 'topic' in check):
        worksheet = get_writable_sheet(sheet_name)
        header = worksheet.row_values(1)

        password_updates = []
        status_updates = []

        password_col = header.index("Password") + 1
        status_col = header.index("ImportStatus") + 1



        for idx, row in enumerate(rows):
            try:
                with transaction.atomic():
                    date_of_birth = row['Date of Birth']

                    try:
                        if not date_of_birth or str(date_of_birth) in ['nan', 'NaT']:  # is not available
                            date_of_birth = None
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
                        logger.error(f"Date of Birth is invalid. {date_of_birth} in sheet {sheet_name} at row {idx + 2}")
                        print(e)

                    try:
                        school_name = row['School'].lower().strip()
                        if 'alim' in school_name:
                            school_name = 'muzafar_alimbayev'
                        else:
                            school_name = 'bukhar_zhyrau'

                    except ValueError as e:
                        school_name = 'muzafar_alimbayev'
                        logger.error(f"School name was not provided correctly in sheet {sheet_name} at row {idx + 2}")
                        print(e)

                    try:
                        user = CustomUser.objects.update_or_create(
                            username=row['Nickname'],
                            defaults=dict(
                                first_name=row['First Name'],
                                last_name=row['Last Name'],
                                email=row['Email'],
                                role=row['Role'],
                                school=school_name,
                                address=row['Address'],
                                phone_number=row['Phone (parent)'],
                                date_of_birth=date_of_birth,
                            )
                        )[0]

                        raw_password = str(row.get("Password", "")).strip()
                        if raw_password == "" or raw_password.lower() in ("nan", "none"):
                            raw_password = generate_password()
                            col_letter = col_to_letter(password_col)
                            password_updates.append({
                                "range": f"{worksheet.title}!{col_letter}{idx + 2}",
                                "values": [[raw_password]]
                            })

                        user.set_password(raw_password)
                        user.save()


                    except (IntegrityError, ValueError, ValidationError) as e:
                        logger.error(e)
                        print(e)
                        continue

                    try:
                        role = row['Role']
                        if role == 'student':
                            process_student(sheet_name, row, idx, admin_id, user)
                        elif role =='teacher':
                            process_teacher(sheet_name, row, idx, admin_id, user)
                        elif role == 'supervisor':
                            process_supervisor(sheet_name, row, idx, admin_id, user)
                        elif role == 'parent':
                            process_parent(sheet_name, row, idx, admin_id, user)

                        col_letter = col_to_letter(status_col)
                        status_updates.append({
                            "range": f"{worksheet.title}!{col_letter}{idx + 2}",
                            "values": [["✅"]]
                        })

                    except Exception as e:
                        col_letter = col_to_letter(status_col)
                        status_updates.append({
                            "range": f"{worksheet.title}!{col_letter}{idx + 2}",
                            "values": [["❌"]]
                        })
                        continue

            except Exception as e:
                col_letter = col_to_letter(status_col)
                status_updates.append({
                    "range": f"{worksheet.title}!{col_letter}{idx + 2}",
                    "values": [["❌"]]
                })
                msg = f" ----- Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
                print(msg)
                logger.error(msg)
                continue

        if password_updates:
            worksheet.spreadsheet.values_batch_update({
                "valueInputOption": "USER_ENTERED",
                "data": password_updates
            })

        if status_updates:
            worksheet.spreadsheet.values_batch_update({
                "valueInputOption": "USER_ENTERED",
                "data": status_updates
            })

