"""
Object-level permission helpers for Qadam Analytics.

These functions check whether a user has permission to access specific objects.
Use these in views after the role_required decorator has verified the user's role.
"""

from django.http import HttpResponseForbidden

from apps.home.models import HomeroomTeacherAssignment, AcademicYear

# Group names for admin-level roles (bypass object-level checks)
ADMIN_GROUPS = ('Admin', 'Supervisor', 'Principal')

# Group names for teacher roles
TEACHER_GROUPS = ('Teacher', 'HomeroomTeacher')

# All staff that work with students (teachers + psychologists)
STAFF_GROUPS = ('Teacher', 'HomeroomTeacher', 'Psychologist')

# Roles allowed to use the club-management API. ClubManager access is further
# limited to assigned clubs at the queryset/object level.
CLUB_MANAGEMENT_GROUPS = ('ClubManager',) + ADMIN_GROUPS


def is_admin_role(user):
    """Check if user has an admin-level role that bypasses object permissions."""
    return user.groups.filter(name__in=ADMIN_GROUPS).exists()


def is_teacher_role(user):
    """Check if user has a teacher role (teacher or homeroom_teacher)."""
    return user.groups.filter(name__in=TEACHER_GROUPS).exists()


def is_staff_role(user):
    """Check if user has a staff role that bypasses object permissions."""
    return user.groups.filter(name__in=STAFF_GROUPS).exists()


def is_club_management_role(user):
    """Check whether a user can enter the club-management API."""
    return user.groups.filter(name__in=CLUB_MANAGEMENT_GROUPS).exists()


def _teacher_teaches_subject(teacher, subject):
    """Check if teacher is assigned to teach a subject via TeachingAssignment."""
    from apps.home.models import TeachingAssignment
    return TeachingAssignment.objects.filter(
        offering__subject=subject,
        teacher=teacher
    ).exists()


def _teacher_teaches_offering(teacher, offering):
    """Check if teacher is assigned to a specific SubjectOffering."""
    from apps.home.models import TeachingAssignment
    return TeachingAssignment.objects.filter(
        offering=offering,
        teacher=teacher
    ).exists()


def _student_enrolled_in_offering(student, offering):
    """Check if student is enrolled in the class group for an offering."""
    from apps.home.models import Enrollment
    return Enrollment.objects.filter(
        student=student,
        class_group=offering.class_group,
        academic_year=offering.academic_year,
        status='active'
    ).exists()


def can_access_subject(user, subject):
    """
    Check if user can access a specific subject.

    Returns True if:
    - User is admin/supervisor/principal
    - User is a teacher assigned to teach the subject
    - User is a student enrolled in a class where this subject is offered
    """
    if is_admin_role(user):
        return True

    # Teacher check - via TeachingAssignment
    if is_teacher_role(user):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return _teacher_teaches_subject(teacher, subject)
        except Teacher.DoesNotExist:
            return False

    # Student check - via Enrollment
    if user.is_student():
        from apps.authentication.models import Student
        from apps.home.models import Enrollment, SubjectOffering
        try:
            student = Student.objects.get(user=user)
            # Check if student is enrolled in any class where this subject is offered
            student_enrollments = Enrollment.objects.filter(
                student=student, status='active'
            ).values_list('class_group_id', 'academic_year_id')

            for class_group_id, academic_year_id in student_enrollments:
                if SubjectOffering.objects.filter(
                    subject=subject,
                    class_group_id=class_group_id,
                    academic_year_id=academic_year_id
                ).exists():
                    return True
            return False
        except Student.DoesNotExist:
            return False

    return False


def can_access_lesson(user, lesson):
    """
    Check if user can access a specific lesson.

    Returns True if:
    - User is admin/supervisor/principal
    - User is a teacher assigned to the lesson's offering
    - User is a student enrolled in the lesson's offering's class
    """
    if not lesson.offering:
        return is_admin_role(user)

    if is_admin_role(user):
        return True

    # Teacher check
    if is_teacher_role(user):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return _teacher_teaches_offering(teacher, lesson.offering)
        except Teacher.DoesNotExist:
            return False

    # Student check
    if user.is_student():
        from apps.authentication.models import Student
        try:
            student = Student.objects.get(user=user)
            return _student_enrolled_in_offering(student, lesson.offering)
        except Student.DoesNotExist:
            return False

    return False


def can_modify_lesson(user, lesson):
    """
    Check if user can modify a lesson (create topics, grade, etc).

    Returns True if:
    - User is admin/supervisor/principal
    - User is a teacher assigned to the lesson's offering
    """
    if is_admin_role(user):
        return True

    if not lesson.offering:
        return False

    if is_teacher_role(user):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return _teacher_teaches_offering(teacher, lesson.offering)
        except Teacher.DoesNotExist:
            return False

    return False


def can_access_student(user, student):
    """
    Check if user can view a specific student's details.

    Returns True if:
    - User is admin/supervisor/principal
    - User is a teacher who teaches the student (via shared offerings)
    - User is the parent of the student
    - User is the student themselves
    """
    if is_admin_role(user):
        return True

    # Self-access
    if user == student.user:
        return True

    # Teacher check - can see students in their classes
    if is_teacher_role(user):
        from apps.authentication.models import Teacher
        from apps.home.models import TeachingAssignment, Enrollment
        try:
            teacher = Teacher.objects.get(user=user)
            academic_year = AcademicYear.objects.filter(is_active=True).first()
            homeroom = HomeroomTeacherAssignment.objects.filter(teacher=teacher, academic_year=academic_year).first()
            if homeroom:
                enrollment = student.get_current_enrollment()
                if enrollment.class_group_id == homeroom.class_group_id:
                    return True

            teacher_class_groups = TeachingAssignment.objects.filter(
                teacher=teacher
            ).values_list('offering__class_group_id', flat=True)

            return Enrollment.objects.filter(
                student=student,
                class_group_id__in=teacher_class_groups,
                status='active'
            ).exists()
        except Teacher.DoesNotExist:
            return False

    # Parent check
    if user.is_parent():
        from apps.authentication.models import Parent
        try:
            parent = Parent.objects.get(user=user)
            return parent.students.filter(pk=student.pk).exists()
        except Parent.DoesNotExist:
            return False

    if user.is_psychologist():
        return True

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
    if is_teacher_role(user):
        return True

    return False


def can_modify_subject(user, subject):
    """
    Check if user can modify a subject (archive, change status, etc).

    Returns True if:
    - User is admin/supervisor
    - User is a teacher assigned to teach the subject
    """
    if is_admin_role(user):
        return True

    if is_teacher_role(user):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            return _teacher_teaches_subject(teacher, subject)
        except Teacher.DoesNotExist:
            return False

    return False


def can_grade_student(user, lesson, student):
    """
    Check if user can grade a specific student for a lesson.

    Returns True if:
    - User is admin/supervisor
    - User is a teacher assigned to the lesson's offering AND student is enrolled
    """
    if is_admin_role(user):
        return True

    if not lesson.offering:
        return False

    if is_teacher_role(user):
        from apps.authentication.models import Teacher
        try:
            teacher = Teacher.objects.get(user=user)
            # Check teacher is assigned to this offering
            if not _teacher_teaches_offering(teacher, lesson.offering):
                return False
            # Check student is enrolled in the offering's class
            return _student_enrolled_in_offering(student, lesson.offering)
        except Teacher.DoesNotExist:
            return False

    return False


def permission_denied_response(message="You do not have permission to access this resource."):
    """Return a standard 403 Forbidden response."""
    return HttpResponseForbidden(message)


# ---------------------------------------------------------------------------
# DRF Permission Classes (shared across apps)
# ---------------------------------------------------------------------------
from rest_framework.permissions import BasePermission  # noqa: E402


class IsTeacherAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user) or is_teacher_role(request.user)


class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user)


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user)


class IsTeacherRole(BasePermission):
    def has_permission(self, request, view):
        return is_teacher_role(request.user)


class IsAdminOrTeacherRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user) or is_teacher_role(request.user)


class IsParent(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_parent()


class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_student()


class CanAccessStudent(BasePermission):
    def has_object_permission(self, request, view, obj):
        return can_access_student(request.user, obj)


class CanModifyStudent(BasePermission):
    def has_object_permission(self, request, view, obj):
        return can_modify_student(request.user, obj)


class CanAccessTeacher(BasePermission):
    def has_object_permission(self, request, view, obj):
        return can_access_teacher(request.user, obj)


class CanAccessSubject(BasePermission):
    def has_object_permission(self, request, view, obj):
        return can_access_subject(request.user, obj)


class CanModifySubject(BasePermission):
    def has_object_permission(self, request, view, obj):
        return can_modify_subject(request.user, obj)


class IsPsychologist(BasePermission):
    def has_permission(self, request, view):
        return request.user.groups.filter(name='Psychologist').exists()


class IsPsychologistOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            is_admin_role(request.user)
            or request.user.groups.filter(name='Psychologist').exists()
        )


class IsHomeroomTeacher(BasePermission):
    def has_permission(self, request, view):
        return request.user.groups.filter(name='HomeroomTeacher').exists()


class IsHomeroomTeacherOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            is_admin_role(request.user)
            or request.user.groups.filter(name='HomeroomTeacher').exists()
        )


class IsStaffOrAdmin(BasePermission):
    """Any teacher subtype, psychologist, or admin."""
    def has_permission(self, request, view):
        return (
            is_admin_role(request.user)
            or request.user.groups.filter(name__in=STAFF_GROUPS).exists()
        )


class IsClubManagementRole(BasePermission):
    """ClubManager, Admin, Supervisor, or Principal."""

    def has_permission(self, request, view):
        return is_club_management_role(request.user)
