from rest_framework.permissions import BasePermission

from core.permissions import (
    is_admin_role, is_teacher_role,
    can_access_student, can_modify_student,
    can_access_teacher, can_access_subject, can_modify_subject,
)


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


class IsTeacherAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return (
            is_admin_role(request.user)
            or is_teacher_role(request.user)
        )


class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user)


class IsParent(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_parent()
