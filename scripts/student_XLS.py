import os
import django
import pandas as pd

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db.models import signals
from apps.authentication import models as auth_models
from apps.authentication.models import CustomUser, Student
from apps.home.models import Subject, ClassRoom, AcademicYear


# df = pd.read_excel('qadam-analytics/apps/data_tables/custom_user_table.xlsx')
#fignya does not run correctly, because the paths become dependent on each other???
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
file_path = os.path.join(BASE_DIR, '/home/yersultan/Downloads/Students info Platform (1).xlsx')

dfs = pd.read_excel(file_path, sheet_name=None)
# print(df.columns()) #first 5 rows. df.head(10) --> 10 rows

signals.post_save.disconnect(auth_models.registration_email_post_send, sender=CustomUser)
for sheet_name, df in dfs.items():
    for _, row in df.iterrows():
        date_of_birth = row['Date of Birth']

        if pd.isna(date_of_birth):
            date_of_birth = None
        else:
            if isinstance(date_of_birth, str):
                cleaned = date_of_birth.strip().replace("ж", "")
                date_of_birth = pd.to_datetime(cleaned, format="%d.%m.%Y", errors="coerce")
            else:
                date_of_birth = pd.to_datetime(date_of_birth, errors="coerce")

            if pd.isna(date_of_birth):
                date_of_birth = None
            else:
                date_of_birth = date_of_birth.date()





        user= CustomUser.objects.update_or_create(
            username=row['Nickname'],
            defaults=dict(
                first_name=row['First Name'],
                last_name=row['Last Name'],
                email=row['Email'],
                role=row['Role'],
                school=row['School'],
                address=row['Address'],
                phone_number=row['Phone (parent)'],
                date_of_birth=date_of_birth,
            )
        )[0]
        user.set_password(str(row['Password']))

        academic_year= AcademicYear.objects.update_or_create(year=row['Academic Year'])[0]
        class_room= ClassRoom.objects.update_or_create(
            name=row['Class'],
            capacity=26,
            academic_year=academic_year
        )[0]

        school_group_id = (
            1 if row['School Group (Orda)'] == 'Ак'
            else 2 if row['School Group (Orda)'] == 'Улы'
            else 3 if row['School Group (Orda)'] == 'Кок'
            else 4
        )

        student = Student.objects.update_or_create(
            user=user,
            defaults=dict(
                academic_year=academic_year,
                classroom=class_room,
                school_group_id=school_group_id
            )
        )[0]

        academic_year = AcademicYear.objects.update_or_create(year=row['Academic Year'])[0]
        subject= Subject.objects.update_or_create(
            name=row['Subjects'],
            academic_year=academic_year,
            defaults={
                "language_group": "KAZ",
                "status": "active",
                "progress": 0,
                "average_points": 0,
                "maximum_points": 100,
            }
        )[0]
        student.subjects.add(subject)
        student.save()
