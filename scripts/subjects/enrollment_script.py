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
        enrollment = Enrollment.objects.filter(
            student=student,
            academic_year=academic_year,
            status='active'
        ).first()

        if enrollment:
            # Update existing active enrollment
            enrollment.class_group = class_group
            enrollment.save()
        else:
            # Create new active enrollment
            Enrollment.objects.create(
                student=student,
                class_group=class_group,
                academic_year=academic_year,
                status='active'
            )

    except IntegrityError as e:
        msg = f'Error while adding Enrollment for student: {student.user.get_full_name()}'
        logger.error(msg)
        raise
