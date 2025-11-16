from django.db import transaction
from apps.authentication.models import Student
from apps.home.models import Subject, ClassRoom, AcademicYear
from scripts.utils.logging_config import logger

def process_student(sheet_name, row, idx, admin_id, user):
    try:
        with transaction.atomic():

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


            class_room = ClassRoom.objects.update_or_create(
                name=row['Class'],
                capacity=26,
                academic_year=academic_year
            )[0]


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
            school_group_value = row['School Group (Orda)'].lower()


            if school_group_value not in school_group_map:
                print(
                    f"Invalid school group '{school_group_value}' in sheet {sheet_name}, row {idx + 2}. "
                    f"Expected one of: {list(school_group_map.keys())}"
                )
            school_group_id = school_group_map[school_group_value]


            student = Student.objects.update_or_create(
                user=user,
                defaults=dict(
                    academic_year=academic_year,
                    classroom=class_room,
                    school_group_id=school_group_id
                )
            )[0]

            subject = Subject.objects.update_or_create(
                name=row['Subjects'],
                academic_year=academic_year,
                defaults={
                    "language_group": "KAZ",
                    "status": "active",
                    "progress": 0,
                    "average_points": 0,
                    "maximum_points": 100,
                    "added_by_id": admin_id,
                }
            )[0]
            student.subjects.add(subject)

            student.save()

    except Exception as e:
        msg = f" ----- Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
        print(msg)
        logger.error(msg)