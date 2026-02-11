from django.db import transaction
from apps.authentication.models import Teacher
from apps.home.models import Subject, AcademicYear

from scripts.utils.logging_config import logger

def process_teacher(sheet_name, row, idx, admin_id, user):
    '''
    gender
    academic_degree
    employment_type
    subjects -->  required
    occupation
    working_hours
    classroom
    '''

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

            try:
                gender = row['Gender']
                female_initials = {'f', 'F'}
                male_initials = {'m', 'M'}
                if gender[0] in female_initials:
                    gender = "female"
                elif gender[0] in male_initials:
                    gender = "male"
                else:
                    raise ValueError("Gender not recognized")
            except ValueError as e:
                logger.debug(f"Gender not recognized: sheet {sheet_name}, row {idx + 2} — {e}")

            try:
                employment_type = row['EmploymentType']
                if 'full' in employment_type.lower():
                    employment_type = "Full-Time"
                elif 'part' in employment_type.lower():
                    employment_type = "Part-Time"
                else:
                    employment_type = ""
                    raise ValueError("Employment type not recognized")
            except ValueError as e:
                logger.debug(f"Employment type not recognized: sheet {sheet_name}, row {idx + 2} — {e}")


            teacher = Teacher.objects.update_or_create(
                user=user,
                defaults=dict(
                    gender=gender,
                    academic_degree=row['AcademicDegree'],
                    employment_type=employment_type,
                    occupation=row['Occupation'],
                    working_hours=row['WorkingHours'],
                )
            )
            # setting classroom and subjects

            classroom_name = row['ClassRoom']
            classroom = None
            if classroom_name != '':
                classroom = ClassRoom.objects.update_or_create(
                    name=classroom_name,
                    capacity = 26,
                    academic_year = academic_year,
                )[0]

            try:
                all_subjects = list(Subject.objects.all())
                all_subject_names = set()
                for sub in all_subjects:
                    all_subject_names.add(sub.name)

                temp = row['Subjects']

                if len(temp) == 0:
                    raise ValueError(f"Subjects are empty: : sheet {sheet_name}, row {idx + 2} — {e}")

                subjects_to_add = [s.strip() for s in temp.split('/') if s.strip()]

                subjects = []
                for sub in subjects_to_add:
                    if sub not in all_subject_names:
                        Subject.objects.create(
                            name=sub,
                            academic_year="2025/2026",  # auto assign zhasaityn method tappai kaldym
                            defaults={
                                "language_group": "KAZ",
                                "status": "active",
                                "progress": 0,
                                "average_points": 0,
                                "maximum_points": 100,
                                "added_by_id": admin_id,
                            }
                        )
                    subjects.append(sub)

                teacher.classroom = classroom
                teacher.subjects = subjects
                teacher.save()

            except ValueError as e:
                logger.debug(e)

    except Exception as e:
        msg = f"---->>>Transaction error: sheet {sheet_name}, row {idx + 2} — {e}"
        logger.error(msg)
