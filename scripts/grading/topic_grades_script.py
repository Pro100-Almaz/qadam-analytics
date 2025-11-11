import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from scripts.reading_data import get_sheets_data
from scripts.utils.logging_config import logger

from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError

from apps.lesson.models import Topic, Lesson
from apps.lesson.models import TopicGrade
from apps.authentication.models import Student


dfs = get_sheets_data()

for sheet_name, rows in dfs.items():
    check = sheet_name.lower()
    if "grade" in check or "topicgrade" in check or "grades" in check:
        for idx, row in enumerate(rows):
            try:
                with transaction.atomic():

                    lesson_title = str(row.get("LessonTitle", "")).strip()
                    if not lesson_title:
                        raise ValueError(f"Missing LessonTitle (row {idx + 2})")

                    lesson = Lesson.objects.filter(title=lesson_title).first()
                    if not lesson:
                        logger.error(
                            f"Lesson '{lesson_title}' not found — skipping row {idx + 2}"
                        )
                        continue


                    topic_title = str(row.get("TopicTitle", "")).strip()
                    if not topic_title:
                        raise ValueError(f"Missing TopicTitle (row {idx + 2})")

                    topic = Topic.objects.filter(
                        lesson=lesson,
                        title=topic_title
                    ).first()

                    if not topic:
                        logger.error(
                            f"Topic '{topic_title}' not found for lesson '{lesson.title}' — skipping row {idx + 2}"
                        )
                        continue


                    student_username = str(row.get("StudentNickname", "")).strip()
                    if not student_username:
                        raise ValueError(f"Missing StudentNickname (row {idx + 2})")

                    student = Student.objects.filter(user__username=student_username).first()
                    if not student:
                        logger.error(
                            f"Student '{student_username}' not found — skipping row {idx + 2}"
                        )
                        continue


                    try:
                        grade = float(row.get("Grade", 0))
                        if grade < 0:
                            raise ValueError
                        if grade > 100:
                            logger.warning(f"Grade >100: {grade}, clamping to 100 (row {idx + 2})")
                            grade = 100

                    except Exception:
                        logger.warning(
                            f"Invalid Grade — defaulting to 0 (row {idx + 2})"
                        )
                        grade = 0

                    comment = str(row.get("Comment", "")).strip()

                    raw_flag = str(row.get("CommentSelected", "")).strip().lower()
                    comment_selected = raw_flag in ["1", "true", "yes"]

                    topic_grade = TopicGrade.objects.update_or_create(
                        topic=topic,
                        student=student,
                        defaults=dict(
                            grade=grade,
                            comment=comment,
                            comment_selected=comment_selected,
                        )
                    )[0]

                    logger.info(
                        f"(Topic={topic.title}, Student={student.user.username}, row={idx + 2})"
                    )

            except (IntegrityError, ValidationError, ValueError) as e:
                logger.error(f"Error processing TopicGrade row {idx + 2}: {e}")
                print(e)
                continue

            except Exception as e:
                msg = f"Unexpected topic grade import error (sheet {sheet_name}, row {idx + 2}): {e}"
                print(msg)
                logger.error(msg)
                continue
