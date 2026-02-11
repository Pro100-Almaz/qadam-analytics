from django import template

register = template.Library()


def _is_management(user):
    """Check if user has a management-level role (Admin, Supervisor, Principal)."""
    return user.is_admin() or user.is_manager() or user.is_principal() or user.is_superuser


@register.simple_tag(takes_context=True)
def can_manage(context):
    user = context["user"]
    if not user.is_authenticated:
        return False
    return _is_management(user)


@register.simple_tag(takes_context=True)
def can_see_students(context):
    user = context["user"]
    if not user.is_authenticated:
        return False
    return _is_management(user) or user.is_teacher()


@register.simple_tag(takes_context=True)
def can_add_user(context):
    user = context["user"]
    if not user.is_authenticated:
        return False
    return _is_management(user)


@register.simple_tag(takes_context=True)
def parent_students(context):
    user = context["user"]
    if user.is_authenticated and user.is_parent():
        return user.get_students() or []
    return []
