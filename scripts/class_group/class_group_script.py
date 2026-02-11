'''
-Idea --> split the classroom name into the grade and letter parts
fields:
=AcademicYear --> FK
=GradeLevel --> FK
=Letter
'''
from apps.home.models import ClassGroup, GradeLevel
from scripts.utils.logging_config import logger

def add_class_group(academic_year, class_name: str):
    # 1 --> split the class_name into the integer and letter parts
    integer_part = []
    string_part = []

    for c in class_name:
        if 29 < ord(c) < 58:
            integer_part.append(c)
        else:
            string_part.append(c)

    integer_value = int(''.join(integer_part))
    grade_level = GradeLevel.objects.update_or_create(number = integer_value)[0]
    string_value = ''.join(string_part)

    try:
        return ClassGroup.objects.update_or_create(
            academic_year = academic_year,
            grade_level = grade_level,
            letter = string_value
        )[0]
    except Exception as e:
        msg = 'There was a problem adding this class group'
        print(e)
        logger.error(msg)
