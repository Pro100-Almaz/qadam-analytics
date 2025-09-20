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
file_path = os.path.join(BASE_DIR, '')

df = pd.read_excel(file_path)
# print(df.columns()) #first 5 rows. df.head(10) --> 10 rows

signals.post_save.disconnect(auth_models.registration_email_post_send, sender=CustomUser)
for _, row in df.iterrows():
    user, _ = CustomUser.objects.update_or_create(
        username=row['Nickname'],
        defaults=dict(
            first_name=row['First Name'],
            last_name=row['Last Name'],
            email=row['Email'],
            role=row['Role'],
            school=row['School'],
            address=row['Address'],
            phone_number=row['Phone (parent)'],
            date_of_birth=row['Date of Birth'],
        )
    )
    user.set_password(str(row['Password']))

    academic_year, _ = AcademicYear.objects.get_or_create(year=row['Academic Year'])
    class_room, _ = ClassRoom.objects.get_or_create(
        name=row['Class'],
        capacity=26,
        academic_year=academic_year
    )

    school_group_id = (
        1 if row['School Group (Orda)'] == 'Ак'
        else 2 if row['School Group (Orda)'] == 'Улы'
        else 3 if row['School Group (Orda)'] == 'Кок'
        else 4
    )

    student = Student.objects.create(
        user=user,
        academic_year=academic_year,
        classroom=class_room,
        school_group_id=school_group_id,
    )

    academic_year, _ = AcademicYear.objects.get_or_create(year=row['Academic Year'])
    subject, _ = Subject.objects.get_or_create(
        name=row['Subjects'],
        academic_year=academic_year,
        defaults={
            "language_group": "KAZ",
            "status": "active",
            "progress": 0,
            "average_points": 0,
            "maximum_points": 100,
        }
    )
    student.subjects.add(subject)
    student.save()
