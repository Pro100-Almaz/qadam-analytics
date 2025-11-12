import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from scripts.reading_data import get_sheets_data
from scripts.writing_data import get_writable_sheet
from scripts.users.get_admin import get_admin_id
from scripts.utils.logging_config import logger

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.authentication.models import CustomUser, Teacher
from apps.home.models import AcademicYear, Subject

dfs = get_sheets_data()

admin_id = 0

def main():
    global admin_id
    admin_id = get_admin_id()

if __name__ == "__main__":
    main()

for sheet_name, rows in dfs.items():
    check = sheet_name.lower()
    if 'subject' in check:
        worksheet = get_writable_sheet(sheet_name)
        for idx, row in enumerate(rows):
            try:
                with transaction.atomic():

                    name = row['Name'].strip()
                    if not name:
                        raise ValueError("Name cannot be empty")

                    status = str(row['Status'].strip())
                    if status not in ["active", "planned", "disabled", "archived"]:
                        logger.warning(
                            f"Invalid status: {status}.  Status will be disabled. (sheet: {sheet_name}, row {idx + 2})")
                        status = "disabled"

                    language = str(row.get('LanguageGroup', "kaz")).lower().strip()

                    if language in ["kaz", "каз", "қаз", "қазақ", "kazakh", "qazaq", "qaz", "казахсикй"]:
                        language = "KAZ"
                    elif language in ["rus", 'рус', 'russian', "русский"]:
                        language = "RUS"
                    elif language in ['eng', 'en', 'english', "анг", "английский", "ағылшын"]:
                        language = "ENG"
                    else:
                        logger.warning(
                            f"Invalid language '{language}' in sheet {sheet_name}, row {idx + 2}. Defaulting to 'kaz'"
                        )
                        language = "KAZ"


                    try:
                        maximum_points = int(row.get("MaximumPoints", 100))
                        if maximum_points > 100 or maximum_points < 1:
                            raise ValueError
                    except Exception:
                        logger.error(f"Invalid MaximumPoints in sheet {sheet_name}, row {idx+2}. Defaulting to 100.")
                        maximum_points = 100

                    teacher = None
                    teacher_username = str(row['Teacher']).strip()

                    if teacher_username:
                        teacher = Teacher.objects.filter(user__username=teacher_username).first()
                        if not teacher:
                            logger.warning(
                                f"Teacher '{teacher_username}' not found — setting to NULL "
                                f"(sheet {sheet_name}, row {idx + 2})")
                    else:
                        logger.warning(
                            f"No teacher username provided — setting to NULL "
                            f"(sheet {sheet_name}, row {idx + 2})"
                        )

                    added_by = None
                    adder_username = row['AddedBy'].strip()
                    if adder_username:
                        added_by = CustomUser.objects.filter(username=adder_username).first()
                        if not added_by:
                            added_by = CustomUser.objects.get(id=admin_id)
                    else:
                        added_by = CustomUser.objects.get(id=admin_id)


                    try:
                        year = str(row['AcademicYear']).strip()
                        if (len(year) == 9) and ('/' in year):
                            academic_year = AcademicYear.objects.update_or_create(year=year)[0]
                        else:
                            raise ValueError(
                                f"Academic Year is not provided in expected format for '{row['AcademicYear']}'")

                    except ValueError as e:
                        logger.error(f"Academic Year is not provided in expected format for '{row['AcademicYear']}'. "
                                     f"expected format: yyyy/yyyy")
                        print(e)
                        continue

                    try:
                        subject = Subject.objects.update_or_create(
                            name=name,
                            academic_year=academic_year,
                            defaults=dict(
                                status=status,
                                language_group = language.upper(),
                                maximum_points = maximum_points,
                                teacher = teacher,
                                added_by = added_by
                            )
                        )[0]

                        logger.info(
                            f"(Subject '{subject.name}', sheet: {sheet_name}, row {idx + 2})"
                        )
                        import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                        worksheet.update_cell(idx + 2, import_status_col, "✅")

                    except Exception as e:
                        import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                        worksheet.update_cell(idx + 2, import_status_col, "❌")
                        continue

            except (IntegrityError, ValidationError, ValueError) as e:
                logger.error(f"Error processing subject in sheet {sheet_name}, row {idx + 2}: {e}")
                print(e)
                continue

            except Exception as e:
                import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                worksheet.update_cell(idx + 2, import_status_col, "❌")

                msg = f" ----- Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
                print(msg)
                logger.error(msg)
                continue
