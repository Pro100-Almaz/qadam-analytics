print('xxxxxx')
import os
import sys

import django

if __name__ == '__main__':
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.append(BASE_DIR)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    django.setup()

from django.db import transaction
from apps.authentication.models import Student
from apps.home.models import Subject, AcademicYear
from scripts.class_group.class_group_script import add_class_group
from scripts.subjects.enrollment_script import add_enrollment
from scripts.subjects.subject_offering_script import add_subject_offering
from scripts.utils.logging_config import logger

'''
current student model:
Subjects already done
SchoolGroup(Orda) already done
AcademicYear already done

for the full implementation of the script need extra validations:
1) ClassRoom == ClassGroup --> run class_group_script --> uses classroom value and AcademicYear
2) SubjectOffering == subject_offering_script --> uses subject, ClassGroup, AcademicYear
3) Finally Enrollment == uses Status(needs to be added to the excell fields), student, classGroup, AcademicYear, start_date+end_date(add to excell)
4) extra --> TeachingAssignment --> uses Role Choices, SubjectOffering, Teacher
'''

def process_student(sheet_name, row, idx, admin_id, user):
    try:
        with transaction.atomic():
            #1) AcademicYear
            try:
                year = str(row['Academic Year']).strip()
                if (len(year) == 9) and ('/' in year):
                    academic_year = AcademicYear.objects.update_or_create(year=row['Academic Year'])[0]
                else:
                    raise ValueError(f"Academic Year is not provided in expected format for '{row['Academic Year']}'")

            except ValueError as e:
                logger.error(f"Academic Year is not provided in expected format for '{row['Academic Year']}'. "
                             f"expected format: yyyy/yyyy")
                print(e)

            #2) ClassGroup
            class_group = add_class_group(academic_year, row['Class']) # --> may through an exception

            school_group_map = {
                'ақ': 1,
                'ұлы': 2,
                'көк': 3,
                'алтын': 4,
                'aq': 1,
                'uly': 2,
                'kok': 3,
                'altyn': 4,

            }
            school_group_value = row['School Group (Orda)'].lower().strip()

            if school_group_value not in school_group_map:
                print(
                    f"Invalid school group '{school_group_value}' in sheet {sheet_name}, row {idx + 2}. "
                    f"Expected one of: {list(school_group_map.keys())}"
                )
            school_group_id = school_group_map[school_group_value]

            # 3) creating the student
            student = Student.objects.update_or_create(
                user=user,
                defaults=dict(
                    academic_year=academic_year,
                    school_group_id=school_group_id
                )
            )[0]

            rs = row['Subjects']
            raw_subjects = [s.strip() for s in rs.split('/') if s.strip()]
            subjects_to_add = set()
            print(raw_subjects)

            for sub in raw_subjects:
                subject = Subject.objects.update_or_create(
                    name=sub,
                    defaults={
                        "language_group": "KAZ",
                        "status": "active",
                        "added_by_id": admin_id,
                    }
                )[0]
                subjects_to_add.add(subject.id)
                add_subject_offering(subject, academic_year, class_group)

            student.subjects.add(*subjects_to_add)
            student.save()

            #Handling Enrollments
            add_enrollment(student, class_group, academic_year)

    except Exception as e:
        msg = f" ----- Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
        print(msg)
        logger.error(msg)