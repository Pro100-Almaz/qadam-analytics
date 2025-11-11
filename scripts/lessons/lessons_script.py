import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from scripts.reading_data import get_sheets_data
from scripts.utils.logging_config import logger

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.lesson.models import Lesson, LessonGroup
from apps.home.models import Subject

dfs = get_sheets_data()

for sheet_name, rows in dfs.items():
    check = sheet_name.lower()

    if "lesson" in check:  # Detect lesson sheet
        for idx, row in enumerate(rows):

            try:
                with transaction.atomic():

                    title = str(row.get("Title", "")).strip()
                    if not title:
                        raise ValueError(f"Lesson Title cannot be empty (sheet: {sheet_name}, row {idx + 2})")

                    description = str(row.get("Description", "")).strip()

                    subject = None
                    subject_name = str(row.get("Subject", "")).strip()
                    if subject_name:
                        subject = Subject.objects.filter(name=subject_name).first()
                        if not subject:
                            logger.warning(
                                f"Subject '{subject_name}' not found. Setting NULL. "
                                f"(sheet: {sheet_name}, row {idx + 2})")
                    else:
                        logger.warning(
                            f"No subject provided --> (sheet: {sheet_name}, row {idx + 2})")

                    try:
                        max_points = int(row.get("MaximumPoints", 100))
                        if max_points < 1 or max_points > 100:
                            raise ValueError
                    except Exception:
                        logger.warning(
                            f"Invalid MaximumPoints — defaulting to 100 (sheet: {sheet_name}, row {idx + 2})"
                        )
                        max_points = 100

                    try:
                        quarter = int(row.get("Quarter", 1))
                        if not (1 <= quarter <= 4):
                            raise ValueError
                    except Exception:
                        logger.warning(
                            f"Invalid Quarter — defaulting to 1 (sheet: {sheet_name}, row {idx + 2})"
                        )
                        quarter = 1

                    try:
                        unit = int(row.get("Unit", 1))
                        if not (1 <= unit <= 15):
                            raise ValueError
                    except Exception:
                        logger.warning(
                            f"Invalid Unit — defaulting to 1 (sheet: {sheet_name}, row {idx + 2})"
                        )
                        unit = 1

                    status = str(row.get("Status", "pending")).lower().strip()
                    if status not in ["pending", "completed", "delayed", "on schedule"]:
                        logger.warning(
                            f"Invalid status '{status}'. Defaulting to 'pending' "
                            f"(sheet: {sheet_name}, row {idx + 2})"
                        )
                        status = "pending"

                    group = None
                    group_name = str(row.get("Group", "")).strip()

                    if group_name:
                        group = LessonGroup.objects.filter(name=group_name).first()
                        if not group:
                            logger.warning(
                                f"LessonGroup '{group_name}' not found"
                                f"(sheet: {sheet_name}, row {idx + 2})"
                            )

                    lesson, created = Lesson.objects.update_or_create(
                        title=title,
                        subject=subject,
                        quarter=quarter,
                        unit=unit,
                        defaults=dict(
                            description=description,
                            maximum_points=max_points,
                            status=status,
                            group=group,
                        )
                    )

                    logger.info(
                        f"{'Created' if created else 'Updated'} Lesson '{lesson.title}' "
                        f"(sheet: {sheet_name}, row {idx + 2})"
                    )

            except (IntegrityError, ValidationError, ValueError) as e:
                logger.error(f"Error processing lesson (sheet {sheet_name}, row {idx + 2}): {e}")
                print(e)
                continue

            except Exception as e:
                msg = f"----- Unexpected lesson import error: sheet {sheet_name}, row {idx + 2} — {e}"
                print(msg)
                logger.error(msg)
                continue
