
from django.db import transaction
from apps.authentication.models import Parent, CustomUser, Student
from scripts.utils.logging_config import logger


def process_parent(sheet_name, row, idx, admin_id, user):
    try:
        with transaction.atomic():
            student_field = str(row['Students']).strip()
            if not student_field:
                logger.warning(f"No students linked: sheet {sheet_name}, row {idx + 2}")
                return

            raw_names = [s.strip() for s in student_field.replace(',', '/').split('/') if s.strip()]

            linked_students = []

            for nickname in raw_names:
                try:
                    student_user = CustomUser.objects.get(username=nickname, role=CustomUser.ROLE_STUDENT)
                    student = Student.objects.get(user=student_user)
                    linked_students.append(student)
                except CustomUser.DoesNotExist:
                    logger.warning(f"Student user not found: {nickname} (sheet {sheet_name}, row {idx + 2})")
                except Student.DoesNotExist:
                    logger.warning(f"Student record not found for user: {nickname} (sheet {sheet_name}, row {idx + 2})")
            parent, _ = Parent.objects.update_or_create(user=user)
            if linked_students:
                parent.students.set(linked_students)
                parent.save()

    except Exception as e:
        msg = f"---->>>Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
        logger.error(msg)
