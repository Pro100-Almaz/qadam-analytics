'''
Status
Student
Class Group
Academic Year
Start_date
End_date
Notes
'''
from django.db import IntegrityError

from apps.home.models import Enrollment
from scripts.utils.logging_config import logger


def add_enrollment(student, class_group, academic_year):
    try:
        # Major groups replace the student's current major enrollment for the
        # year; minor groups are added alongside whatever they already have.
        Enrollment.enroll_student(student, class_group, academic_year)

    except IntegrityError as e:
        msg = f'Error while adding Enrollment for student: {student.user.get_full_name()}'
        logger.error(msg)
        raise
