from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def can_see_students(context):
    user = context["user"]
    return user.is_authenticated and (user.is_manager or user.is_superuser or user.is_teacher)

@register.simple_tag(takes_context=True)
def can_add_user(context):
    user = context["user"]
    return user.is_authenticated and (user.is_manager or user.is_superuser)

@register.simple_tag(takes_context=True)
def parent_students(context):
    user = context["user"]
    if user.is_authenticated and getattr(user, "is_parent", False):
        return getattr(user, "get_students", lambda: [])()
    return []
