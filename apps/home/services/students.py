from django.contrib import messages

from apps.authentication.models import MAX_AVATAR_SIZE_MB, MAX_AVATAR_SIZE_BYTES
from apps.home.repo import students as students_repo


def change_student_avatar(student_id : int, avatar_file):
    avatar_file = avatar_file
    return students_repo.update_student_avatar(student_id, avatar_file)
