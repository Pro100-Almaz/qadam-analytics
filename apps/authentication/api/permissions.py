from rest_framework.permissions import BasePermission

from core.permissions import is_admin_role, is_teacher_role, ADMIN_GROUPS


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user)


class IsTeacherRole(BasePermission):
    def has_permission(self, request, view):
        return is_teacher_role(request.user)


class IsAdminOrTeacherRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user) or is_teacher_role(request.user)
