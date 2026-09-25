"""The system checks in core.checks must actually fail things.

"A new model fails the build until someone classifies it" is the sentence the
whole tenancy design leans on. A check that cannot fail is worse than no check,
so each of these breaks a real model and asserts the right error id comes back.
"""

import pytest
from django.db import models

from apps.authentication.models import School, Student
from apps.home.models import GradeLevel, Subject
from core import checks as tenancy_checks
from core.checks import (
    check_every_model_is_classified,
    check_no_nullable_link_in_school_path,
    check_school_paths_resolve,
    check_school_scope_mode_is_valid,
    check_scoped_models_have_a_scoped_manager,
)


def _ids(errors):
    return sorted(e.id for e in errors)


def test_the_tree_is_currently_clean():
    """Guards against a check that silently stopped matching anything."""
    assert check_every_model_is_classified() == []
    assert check_school_paths_resolve() == []
    assert check_no_nullable_link_in_school_path() == []
    assert check_scoped_models_have_a_scoped_manager() == []
    assert check_school_scope_mode_is_valid() == []


def test_a_model_is_actually_walked():
    """If _tenant_models() ever returns nothing, every check passes trivially."""
    labels = {m._meta.label for m in tenancy_checks._tenant_models()}
    assert 'home.Subject' in labels
    assert 'lesson.TopicGrade' in labels
    assert len(labels) > 30
    assert not any(l.startswith('Historical') for l in labels)


def test_unclassified_model_is_an_error(monkeypatch):
    monkeypatch.delattr(Subject, 'SCHOOL_PATH')
    assert _ids(check_every_model_is_classified()) == ['tenancy.E002']


def test_a_model_cannot_be_both_scoped_and_shared(monkeypatch):
    monkeypatch.setitem(tenancy_checks.SHARED_MODELS, 'home.Subject', 'nope')
    assert _ids(check_every_model_is_classified()) == ['tenancy.E001']


def test_shared_model_needs_no_path():
    assert not hasattr(GradeLevel, 'SCHOOL_PATH')
    assert 'home.GradeLevel' in tenancy_checks.SHARED_MODELS


def test_unresolvable_path_is_an_error(monkeypatch):
    monkeypatch.setattr(Subject, 'SCHOOL_PATH', 'not_a_field', raising=False)
    assert _ids(check_school_paths_resolve()) == ['tenancy.E003']


def test_path_that_stops_short_of_school_is_an_error(monkeypatch):
    monkeypatch.setattr(Student, 'SCHOOL_PATH', 'user', raising=False)
    assert _ids(check_school_paths_resolve()) == ['tenancy.E004']


def test_nullable_link_is_an_error(monkeypatch):
    """The SubjectSchedule class of bug, caught mechanically."""
    from apps.lesson.models import SubjectSchedule
    monkeypatch.setattr(SubjectSchedule, 'SCHOOL_PATH', 'offering__school', raising=False)
    errors = check_no_nullable_link_in_school_path()
    assert _ids(errors) == ['tenancy.E005']
    assert 'invisible to EVERY school' in errors[0].hint


def test_the_customuser_exemption_is_narrow(monkeypatch):
    """Only CustomUser.school is exempt, and only with a stated reason."""
    assert list(tenancy_checks.NULLABLE_LINK_EXEMPTIONS) == [
        'authentication.CustomUser.school'
    ]
    monkeypatch.setattr(tenancy_checks, 'NULLABLE_LINK_EXEMPTIONS', {})
    errors = check_no_nullable_link_in_school_path()

    # Asserted as a property rather than a count: §1a rerouted four models onto
    # `student__user__school`, and a hardcoded number would have to be edited
    # every time a path changes — which teaches people to edit it rather than
    # read it. What matters is that CustomUser.school is the ONLY nullable link
    # the tree relies on.
    assert errors, 'the exemption is load-bearing; removing it must fail things'
    assert {e.id for e in errors} == {'tenancy.E005'}
    assert all('CustomUser.school' in e.msg for e in errors), [e.msg for e in errors]


def test_school_itself_is_never_scoped():
    assert not hasattr(School, 'SCHOOL_PATH')
    assert 'authentication.School' in tenancy_checks.SHARED_MODELS


def test_decorative_school_path_is_an_error(monkeypatch):
    """A path with a plain manager reads as isolated and is not."""
    monkeypatch.setattr(
        Subject._meta, 'default_manager', models.Manager(), raising=False,
    )
    errors = check_scoped_models_have_a_scoped_manager()
    assert _ids(errors) == ['tenancy.E006']


def test_customuser_default_manager_is_exempt_on_purpose():
    assert 'authentication.CustomUser' in tenancy_checks.UNSCOPED_DEFAULT_MANAGER
    assert check_scoped_models_have_a_scoped_manager() == []


def test_a_misspelt_scope_mode_is_an_error(settings):
    """A typo in the env var must fail the deploy, not every request.

    `get_scope_mode()` is called from inside `get_queryset()`, so an
    unrecognised SCHOOL_SCOPE_MODE is not a startup failure — it is a 500 on
    every request that touches a scoped model, found in production. This check
    is what turns it into a failed `manage.py check`.
    """
    settings.SCHOOL_SCOPE_MODE = 'enfroce'
    assert _ids(check_school_scope_mode_is_valid()) == ['tenancy.E007']


@pytest.mark.parametrize('mode', ['off', 'warn', 'enforce'])
def test_every_documented_mode_passes(settings, mode):
    settings.SCHOOL_SCOPE_MODE = mode
    assert check_school_scope_mode_is_valid() == []


def test_the_runtime_raise_is_still_the_backstop(settings):
    """The check is the early warning; get_scope_mode stays fail-loud.

    A value set after startup — override_settings in a test, a reload — never
    passes through `manage.py check`, so the raise has to remain.
    """
    from core.tenancy import get_scope_mode

    settings.SCHOOL_SCOPE_MODE = 'enfroce'
    with pytest.raises(ValueError, match='enfroce'):
        get_scope_mode()
