"""
Access rules for the XLSX grade sheets.

Class-group sheet (/grade/classgroup/<id>/)
    The homeroom teacher of that class group, for the year being reported on.
    When a `subject` is given, additionally any teacher assigned to that class
    group's offering of the subject — primary, assistant or substitute alike,
    since the boundary is the offering rather than whoever entered the grades.

Student sheet (/grade/student/<id>/)
    The student, their parents, and the homeroom teacher of their class. When a
    `subject` is given, additionally the teachers of that subject's offering
    for that class, as above.

Admin roles (Admin / Supervisor / Principal) read both, school-wide, matching
every other read endpoint in the project.

Authority comes from the assignment tables rather than from group membership:
a HomeroomTeacherAssignment or TeachingAssignment row is the explicit grant,
and a teacher holding one should not be locked out because their Django group
drifted.
"""

from apps.authentication.models import Parent, Teacher
from apps.home.models import HomeroomTeacherAssignment, TeachingAssignment
from core.permissions import is_admin_role


def _teacher_profile(user):
    return Teacher.objects.filter(user=user).first()


def is_homeroom_teacher_of(user, class_group, academic_year) -> bool:
    if class_group is None or academic_year is None:
        return False
    teacher = _teacher_profile(user)
    if teacher is None:
        return False
    return HomeroomTeacherAssignment.objects.filter(
        teacher=teacher,
        class_group=class_group,
        academic_year=academic_year,
    ).exists()


def teaches_subject_in_class(user, class_group, academic_year, subject_id) -> bool:
    """Whether the user teaches this exact subject to this exact class group."""
    if class_group is None or academic_year is None:
        return False
    teacher = _teacher_profile(user)
    if teacher is None:
        return False
    return TeachingAssignment.objects.filter(
        teacher=teacher,
        offering__class_group=class_group,
        offering__academic_year=academic_year,
        offering__subject_id=subject_id,
    ).exists()


def is_parent_of(user, student) -> bool:
    if not user.is_parent():
        return False
    parent = Parent.objects.filter(user=user).first()
    if parent is None:
        return False
    return parent.students.filter(pk=student.pk).exists()


def can_read_class_group_sheet(user, class_group, academic_year, subject_id=None) -> bool:
    if is_admin_role(user):
        return True
    if is_homeroom_teacher_of(user, class_group, academic_year):
        return True
    if subject_id is not None:
        return teaches_subject_in_class(user, class_group, academic_year, subject_id)
    return False


def can_read_student_sheet(user, student, class_group, academic_year, subject_id=None) -> bool:
    """
    `class_group` / `academic_year` are None when the student has no active
    enrollment. The checks that need them then fail closed, leaving only the
    relationships that hold regardless — self, parent, admin — so that an
    outsider gets a 403 rather than learning the student is unenrolled.
    """
    if is_admin_role(user):
        return True
    if user == student.user:
        return True
    if is_parent_of(user, student):
        return True
    if is_homeroom_teacher_of(user, class_group, academic_year):
        return True
    if subject_id is not None:
        return teaches_subject_in_class(user, class_group, academic_year, subject_id)
    return False
