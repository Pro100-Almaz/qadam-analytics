from rest_framework.permissions import BasePermission

from core.permissions import is_admin_role, is_teacher_role


class IsTeacherAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return is_admin_role(request.user) or is_teacher_role(request.user)
