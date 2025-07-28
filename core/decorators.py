from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from functools import wraps

def role_required(*roles):
    """
    Decorator for views that checks whether a user has a required role.
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
