from django import template

register = template.Library()

# Language code to emoji flag mapping
LANGUAGE_EMOJI = {
    'kaz': '🇰🇿',
    'rus': '🇷🇺',
    'eng': '🇬🇧',
}

LANGUAGE_NAMES = {
    'kaz': 'Казахский',
    'rus': 'Русский',
    'eng': 'Английский',
}


@register.filter
def lang_emoji(lang_code):
    """Convert language code to emoji flag."""
    if not lang_code:
        return ''
    return LANGUAGE_EMOJI.get(lang_code.lower(), lang_code)


@register.filter
def lang_name(lang_code):
    """Convert language code to full name."""
    if not lang_code:
        return ''
    return LANGUAGE_NAMES.get(lang_code.lower(), lang_code)


@register.filter
def lang_with_emoji(lang_code):
    """Convert language code to emoji + name."""
    if not lang_code:
        return ''
    emoji = LANGUAGE_EMOJI.get(lang_code.lower(), '')
    name = LANGUAGE_NAMES.get(lang_code.lower(), lang_code.upper())
    return f"{emoji} {name}"


@register.filter
def get_item(dictionary, key):
    """
    Template filter to get an item from a dictionary using a key
    Usage: {{ dictionary|get_item:key }}
    """
    if not dictionary:
        return None
    try:
        return dictionary.get(key)
    except (AttributeError, TypeError):
        return None

@register.filter
def dict_get(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None