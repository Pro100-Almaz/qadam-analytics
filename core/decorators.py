from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from functools import wraps

# Mapping from legacy role names to Django Group names
ROLE_TO_GROUP = {
    'admin': 'Admin',
    'teacher': 'Teacher',
    'homeroom_teacher': 'HomeroomTeacher',
    'student': 'Student',
    'supervisor': 'Supervisor',
    'principal': 'Principal',
    'parent': 'Parent',
}


def role_required(*roles):
    """
    Decorator for views that checks whether a user has a required role.
    Checks Django Groups first, then falls back to legacy role field.

    Usage:
        @role_required('teacher')
        def view...
        @role_required('admin', 'principal')
        def view...
    """
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = request.user

            # Convert role names to Group names
            group_names = [ROLE_TO_GROUP.get(r, r) for r in roles]

            # Check Groups first
            if user.groups.filter(name__in=group_names).exists():
                return view_func(request, *args, **kwargs)

            # Fallback to legacy role field
            if hasattr(user, 'role') and user.role in roles:
                return view_func(request, *args, **kwargs)

            return HttpResponseForbidden("You do not have permission to access this page.")
        return _wrapped_view
    return decorator


"""
from core.decorators import role_required

@role_required('teacher')
def teacher_only_view(request):
    # Only teachers allowed
    ...

@role_required('admin', 'principal')
def admin_or_principal_view(request):
"""
