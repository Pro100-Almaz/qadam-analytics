"""
django-modeltranslation registrations for apps.home (spec 0006).

Opt-in: only the fields listed here get a column per language in
settings.LANGUAGES (`name_en`, `name_ru`, `name_kk`). Reading `name` returns the
active language — set from Accept-Language by LocaleMiddleware — and falls back
to English. Register another model here, run makemigrations, and it is done.
"""

from modeltranslation.translator import TranslationOptions, register

from apps.home.models import AssignmentCategory


@register(AssignmentCategory)
class AssignmentCategoryTranslationOptions(TranslationOptions):
    fields = ('name',)
    #: An admin must fill in every language; `code` stays language-neutral.
    required_languages = ('en', 'ru', 'kk')
