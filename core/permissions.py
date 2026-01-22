"""
Object-level permission helpers for Qadam Analytics.

These functions check whether a user has permission to access specific objects.
Use these in views after the role_required decorator has verified the user's role.
"""

from django.http import HttpResponseForbidden


# Roles that bypass object-level checks (admins can access everything)
ADMIN_ROLES = ('admin', 'supervisor', 'principal')


def is_admin_role(user):
    """Check if user has an admin-level role that bypasses object permissions."""
    return hasattr(user, 'role') and user.role in ADMIN_ROLES


def can_access_subject(user, subject):
    """
    Check if user can access a specific subject.

    Returns True if:
    - User is admin/supervisor/principal
    - User is the teacher assigned to the subject
    - User is a student enrolled in the subject
    """
    if is_admin_role(user):
        return True

    # Teacher check
    if user.role in ('teacher', 'homeroom_teacher'):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return subject.teacher == teacher
        except Teacher.DoesNotExist:
            return False

    # Student check
    if user.role == 'student':
        from apps.authentication.models import Student
        try:
            student = Student.objects.get(user=user)
            return student.subjects.filter(pk=subject.pk).exists()
        except Student.DoesNotExist:
            return False

    return False


def can_access_lesson(user, lesson):
    """
    Check if user can access a specific lesson.

    Returns True if:
    - User is admin/supervisor/principal
    - User is the teacher of the lesson's subject
    - User is a student enrolled in the lesson's subject
    """
    return can_access_subject(user, lesson.subject)


def can_modify_lesson(user, lesson):
    """
    Check if user can modify a lesson (create topics, grade, etc).

    Returns True if:
    - User is admin/supervisor/principal
    - User is the teacher of the lesson's subject
    """
    if is_admin_role(user):
        return True

    if user.role in ('teacher', 'homeroom_teacher'):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return lesson.subject.teacher == teacher
        except Teacher.DoesNotExist:
            return False

    return False


def can_access_student(user, student):
    """
    Check if user can view a specific student's details.

    Returns True if:
    - User is admin/supervisor/principal
    - User is a teacher who teaches the student (shares a subject)
    - User is the parent of the student
    - User is the student themselves
    """
    if is_admin_role(user):
        return True

    # Self-access
    if user == student.user:
        return True

    # Teacher check - can see students in their subjects
    if user.role in ('teacher', 'homeroom_teacher'):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            # Check if teacher teaches any subject the student is enrolled in
            teacher_subjects = teacher.subjects.all()
            student_subjects = student.subjects.all()
            return teacher_subjects.filter(pk__in=student_subjects).exists()
        except Teacher.DoesNotExist:
            return False

    # Parent check
    if user.role == 'parent':
        from apps.authentication.models import Parent
        try:
            parent = Parent.objects.get(user=user)
            return parent.students.filter(pk=student.pk).exists()
        except Parent.DoesNotExist:
            return False

    return False


def can_modify_student(user, student):
    """
    Check if user can modify a student's profile.

    Returns True if:
    - User is admin/supervisor only
    """
    return is_admin_role(user)


def can_access_teacher(user, teacher):
    """
    Check if user can view a specific teacher's details.

    Returns True if:
    - User is admin/supervisor/principal
    - User is a fellow teacher (can view colleagues)
    - User is the teacher themselves
    """
    if is_admin_role(user):
        return True

    # Self-access
    if user == teacher.user:
        return True

    # Teachers can view other teachers
    if user.role in ('teacher', 'homeroom_teacher'):
        return True

    return False


def can_modify_subject(user, subject):
    """
    Check if user can modify a subject (archive, change status, etc).

    Returns True if:
    - User is admin/supervisor
    - User is the teacher assigned to the subject
    """
    if is_admin_role(user):
        return True

    if user.role in ('teacher', 'homeroom_teacher'):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return subject.teacher == teacher
        except Teacher.DoesNotExist:
            return False

    return False


def can_grade_student(user, lesson, student):
    """
    Check if user can grade a specific student for a lesson.

    Returns True if:
    - User is admin/supervisor
    - User is the teacher of the lesson's subject AND student is enrolled
    """
    if is_admin_role(user):
        return True

    if user.role in ('teacher', 'homeroom_teacher'):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            # Check teacher owns the subject
            if lesson.subject.teacher != teacher:
                return False
            # Check student is enrolled
            return student.subjects.filter(pk=lesson.subject.pk).exists()
        except Teacher.DoesNotExist:
            return False

    return False


def permission_denied_response(message="You do not have permission to access this resource."):
    """Return a standard 403 Forbidden response."""
    return HttpResponseForbidden(message)
