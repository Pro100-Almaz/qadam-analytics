from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from functools import wraps

# Mapping from lowercase role names to Django Group names
# This allows using either 'teacher' or 'Teacher' in @role_required
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
    Decorator for views that checks whether a user belongs to required Groups.

    Accepts both lowercase role names ('teacher') and Group names ('Teacher').

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

            # Convert role names to Group names (handles both formats)
            group_names = [ROLE_TO_GROUP.get(r, r) for r in roles]

            # Check if user belongs to any of the required Groups
            if user.groups.filter(name__in=group_names).exists():
                return view_func(request, *args, **kwargs)

            return HttpResponseForbidden("You do not have permission to access this page.")
        return _wrapped_view
    return decorator
