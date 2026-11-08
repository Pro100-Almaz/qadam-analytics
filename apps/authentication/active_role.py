"""Resolve the frontend's role selection into a request-local grant.

The header is only a selector. Django group membership remains the authority.
Nothing in this module persists the selection beyond the current request.
"""

from rest_framework.exceptions import APIException


ACTIVE_ROLE_HEADER = 'X-Active-Role'

# Canonical frontend role -> one or more Django groups which can select it.
# HomeroomTeacher deliberately collapses into the teacher UI context.
ROLE_GROUPS = {
    'admin': frozenset({'Admin'}),
    'teacher': frozenset({'Teacher', 'HomeroomTeacher'}),
    'student': frozenset({'Student'}),
    'supervisor': frozenset({'Supervisor'}),
    'principal': frozenset({'Principal'}),
    'parent': frozenset({'Parent'}),
    'clubmanager': frozenset({'ClubManager'}),
    'psychologist': frozenset({'Psychologist'}),
}
SUPPORTED_ACTIVE_ROLES = frozenset(ROLE_GROUPS)


class ActiveRoleForbidden(APIException):
    status_code = 403
    default_code = 'active_role_forbidden'

    def __init__(self, code, detail):
        super().__init__({'code': code, 'detail': detail}, code=code)


def _view_class(request):
    django_request = getattr(request, '_request', request)
    match = getattr(django_request, 'resolver_match', None)
    if match is None:
        return None
    return getattr(match.func, 'view_class', None)


def active_role_is_optional(request):
    """Whether this request may authenticate without selecting a role."""
    if request.method in ('OPTIONS',):
        return True

    view_class = _view_class(request)
    if view_class is None:
        return False
    if getattr(view_class, 'active_role_optional', False):
        return True
    methods = getattr(view_class, 'active_role_optional_methods', ())
    return request.method.upper() in methods


def _set_context(request, user, role, assigned_groups):
    request.active_role = role
    request.active_role_groups = frozenset(assigned_groups)
    # Existing permission and service helpers receive a user rather than a
    # request. Authentication creates this user instance for this request, so
    # attaching the same context does not cross a request boundary.
    user._active_role_context_set = True
    user._active_role = role
    user._active_role_groups = frozenset(assigned_groups)


def resolve_active_role(request, user):
    """Validate and attach the active role for an authenticated request."""
    assigned_groups = set(user.groups.values_list('name', flat=True))
    requested = request.headers.get(ACTIVE_ROLE_HEADER)

    if requested is None:
        if active_role_is_optional(request):
            _set_context(request, user, None, assigned_groups)
            return None

        canonical_roles = {
            role for role, groups in ROLE_GROUPS.items()
            if assigned_groups & groups
        }
        if len(canonical_roles) == 1:
            role = canonical_roles.pop()
            _set_context(request, user, role, assigned_groups)
            return role

        if len(canonical_roles) > 1:
            raise ActiveRoleForbidden(
                'active_role_required',
                'X-Active-Role is required for users with multiple roles.',
            )
        raise ActiveRoleForbidden(
            'active_role_not_assigned',
            'The authenticated user has no supported assigned role.',
        )

    if requested not in SUPPORTED_ACTIVE_ROLES:
        raise ActiveRoleForbidden(
            'invalid_active_role',
            'X-Active-Role contains an unsupported role.',
        )

    if not assigned_groups & ROLE_GROUPS[requested]:
        raise ActiveRoleForbidden(
            'active_role_not_assigned',
            'The requested active role is not assigned to this user.',
        )

    _set_context(request, user, requested, assigned_groups)
    return requested


def user_active_role(user):
    """Return `(has_request_context, role)` for a user instance."""
    return (
        bool(getattr(user, '_active_role_context_set', False)),
        getattr(user, '_active_role', None),
    )


def user_has_active_role(user, *roles):
    """Check canonical roles, falling back to groups outside API requests."""
    has_context, active_role = user_active_role(user)
    if has_context:
        return active_role in roles

    wanted_groups = set()
    for role in roles:
        wanted_groups.update(ROLE_GROUPS.get(role, ()))
    return (
        bool(wanted_groups)
        and user.groups.filter(name__in=wanted_groups).exists()
    )


def user_has_active_group(user, group_name):
    """Check an exact group without allowing an inactive role to contribute."""
    has_context, active_role = user_active_role(user)
    if not has_context:
        return user.groups.filter(name=group_name).exists()
    if active_role is None or group_name not in ROLE_GROUPS[active_role]:
        return False
    return group_name in getattr(user, '_active_role_groups', ())
