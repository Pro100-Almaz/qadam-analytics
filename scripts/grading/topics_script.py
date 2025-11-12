import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from scripts.reading_data import get_sheets_data
from scripts.writing_data import get_writable_sheet
from scripts.utils.logging_config import logger

from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError

from apps.lesson.models import Lesson
from apps.lesson.models import Topic

dfs = get_sheets_data()

for sheet_name, rows in dfs.items():
    check = sheet_name.lower()
    if "topic" in check:
        worksheet = get_writable_sheet(sheet_name)
        for idx, row in enumerate(rows):
            try:
                with transaction.atomic():

                    lesson_title = str(row.get("LessonTitle", "")).strip()
                    if not lesson_title:
                        raise ValueError(f"Missing LessonTitle (sheet: {sheet_name}, row {idx + 2})")

                    lesson = Lesson.objects.filter(title=lesson_title).first()
                    if not lesson:
                        logger.error(
                            f"Lesson '{lesson_title}' not found (sheet: {sheet_name}, row {idx + 2})."
                        )
                        continue

                    topic_title = str(row.get("TopicTitle", "")).strip()
                    if not topic_title:
                        raise ValueError(f"Missing Topic Title (sheet: {sheet_name}, row {idx + 2})")

                    try:  # weight
                        weight = float(row.get("Weight", 0))
                        if weight < 0:
                            raise ValueError
                    except Exception:
                        logger.warning(
                            f"Invalid weight — defaulting to 0 (sheet {sheet_name}, row {idx + 2})"
                        )
                        weight = 0

                    parent_topic = None
                    parent_title = str(row.get("ParentTopic", "")).strip()
                    if parent_title:
                        parent_topic = Topic.objects.filter(
                            lesson=lesson,
                            title=parent_title
                        ).first()
                        if not parent_topic:
                            logger.warning(
                                f"ParentTopic '{parent_title}' not found → setting NULL "
                                f"(sheet {sheet_name}, row {idx + 2})"
                            )

                    comment_template = str(row.get("CommentTemplate", "")).strip()

                    try:
                        topic = Topic.objects.update_or_create(
                            lesson=lesson,
                            title=topic_title,
                            defaults=dict(
                                weight=weight,
                                parent=parent_topic,
                                comment_template=comment_template,
                            )
                        )[0]

                        logger.info(f"(Lesson={lesson.title}, row {idx + 2})")

                        import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                        worksheet.update_cell(idx + 2, import_status_col, "✅")

                    except Exception as e:
                        import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                        worksheet.update_cell(idx + 2, import_status_col, "❌")
                        continue

            except (IntegrityError, ValidationError, ValueError) as e:
                logger.error(f"Error processing topic row {idx + 2}: {e}")
                print(e)
                import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                worksheet.update_cell(idx + 2, import_status_col, "❌")
                continue

            except Exception as e:
                msg = f"Unexpected topic import error (sheet {sheet_name}, row {idx + 2}): {e}"
                print(msg)
                logger.error(msg)
                import_status_col = worksheet.row_values(1).index("ImportStatus") + 1
                worksheet.update_cell(idx + 2, import_status_col, "❌")
                continue
