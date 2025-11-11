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

from apps.authentication.models import PsychologicalState
from apps.authentication.models import Student, CustomUser

dfs = get_sheets_data()

for sheet_name, rows in dfs.items():
    check = sheet_name.lower()

    if "psych" in check or "state" in check or "mental" in check:

        for idx, row in enumerate(rows):
            try:
                with transaction.atomic():

                    name = str(row.get("Name", "")).strip()
                    if not name:
                        raise ValueError(f"Name cannot be empty (sheet: {sheet_name}, row {idx + 2})")

                    comment = str(row.get("Comment", "")).strip()

                    try:
                        score = int(row.get("Score", 1))
                        if not (1 <= score <= 5):
                            raise ValueError
                    except Exception:
                        logger.warning(
                            f"Invalid Score '{row.get('Score')}' — defaulting to 1 "
                            f"(sheet: {sheet_name}, row {idx + 2})"
                        )
                        score = 1

                    student_nickname = str(row.get("StudentNickname", "")).strip()
                    if not student_nickname:
                        raise ValueError(
                            f"Missing StudentNickname — cannot create PsychologicalState "
                            f"(sheet: {sheet_name}, row {idx + 2})"
                        )

                    student = Student.objects.filter(user__username=student_nickname).first()
                    if not student:
                        raise ValueError(
                            f"Student '{student_nickname}' not found — skipping row {idx + 2}"
                        )

                    added_by = None
                    adder_username = str(row.get("AddedBy", "")).strip()
                    if adder_username:
                        added_by = CustomUser.objects.filter(username=adder_username).first()
                        if not added_by:
                            logger.warning(
                                f"AddedBy user '{adder_username}' not found — setting added_by=NULL "
                                f"(sheet: {sheet_name}, row {idx + 2})"
                            )
                            added_by = None

                    state = PsychologicalState.objects.create(
                        name=name,
                        comment=comment,
                        student=student,
                        score=score,
                        added_by=added_by
                    )

                    logger.info(
                        f"Created PsychologicalState '{state.name}' "
                        f"(sheet: {sheet_name}, row {idx + 2})"
                    )

            except (IntegrityError, ValidationError, ValueError) as e:
                logger.error(
                    f"Error processing PsychologicalState (sheet: {sheet_name}, row {idx + 2}): {e}"
                )
                print(e)
                continue

            except Exception as e:
                msg = f"Unexpected error in PsychologicalState import (sheet: {sheet_name}, row {idx + 2}): {e}"
                print(msg)
                logger.error(msg)
                continue
