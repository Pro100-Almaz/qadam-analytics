"""Related fields that resolve their queryset per request, not at import.

A DRF serializer's class body runs once, at import — so
`PrimaryKeyRelatedField(queryset=Student.objects.all())` resolves the school
scope when the module loads, with no request and no scope. Under 'enforce' that
raises during `django.setup()`; under 'off'/'warn' it silently bakes an
UNSCOPED queryset that every school then sees for the life of the process.

For a plain `.all()` the fix needs no class: pass the **Manager** instead of a
QuerySet — `queryset=Student.objects`. `RelatedField.get_queryset` calls
`queryset.all()` on whatever it was handed, and on a Manager that re-enters
`get_queryset()`, so the scope applies per request.

That trick does not survive `.select_related(...)`, because the result is a
QuerySet again. This field covers those: it stores the *model* and defers to
`_default_manager` at call time. Overriding `get_queryset` also suppresses
DRF's "must provide a queryset" assertion, so no placeholder is needed.

A cross-school pk then fails validation with a clean
`400 {"student": ["Invalid pk \\"57\\" - object does not exist."]}` rather than
resolving to another tenant's row.
"""

from rest_framework import serializers


class ScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """`PrimaryKeyRelatedField` whose queryset is built per request.

    Usage::

        offering = ScopedPrimaryKeyRelatedField(
            SubjectOffering, select_related=('subject', 'class_group'),
        )
    """

    def __init__(self, model, select_related=(), **kwargs):
        self._model = model
        self._select_related = tuple(select_related)
        super().__init__(**kwargs)

    def get_queryset(self):
        queryset = self._model._default_manager.all()
        if self._select_related:
            queryset = queryset.select_related(*self._select_related)
        return queryset
