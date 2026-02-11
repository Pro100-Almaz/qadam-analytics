'''
Subject(single)
ClassGroup
AcademicYear
'''
from scripts.utils.logging_config import logger

from django.db import IntegrityError

from apps.home.models import Subject, AcademicYear, ClassGroup, SubjectOffering


def add_subject_offering(subject, academic_year : AcademicYear, class_group: ClassGroup):
    try:
        SubjectOffering.objects.update_or_create(
            subject=subject,
            academic_year=academic_year,
            class_group=class_group
        )
    except IntegrityError:
        msg = 'Could not create the subject offering'
        print(msg)
        logger.error(msg)
