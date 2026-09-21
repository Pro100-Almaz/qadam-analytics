"""The uuid<->pk translation §4 depends on, and School's manager wiring.

The JWT design carries the school as a `uuid` on the wire and a `pk` in the
scope ContextVar, so every request that reads the claim crosses this boundary
twice. These pin the properties the cache is allowed to have — and, more
importantly, the ones it is not.
"""

import uuid as uuid_module

import pytest
from django.db import models

from apps.authentication import school_cache
from apps.authentication.models import School, SchoolVisibleManager
from apps.authentication.school_cache import (
    clear_school_cache, school_pk_for_uuid, uuid_for_school_pk,
)
from core.factories import SchoolFactory


@pytest.fixture
def school(db):
    return SchoolFactory(slug='school_a')


# ------------------------------------------------------------ round trip ----

@pytest.mark.django_db
def test_uuid_and_pk_round_trip(school):
    assert school_pk_for_uuid(school.uuid) == school.pk
    assert uuid_for_school_pk(school.pk) == str(school.uuid)


@pytest.mark.django_db
def test_a_uuid_string_in_any_spelling_resolves(school):
    """A JWT claim is a string, and may arrive hyphenated, bare or upper-case."""
    canonical = str(school.uuid)
    for spelling in (canonical, canonical.upper(), canonical.replace('-', '')):
        clear_school_cache()
        assert school_pk_for_uuid(spelling) == school.pk


@pytest.mark.django_db
def test_garbage_returns_none_rather_than_raising(school):
    """The claim is signed, so its origin is trusted — its content is not.

    A ValueError here would be a 500 on an endpoint an attacker can reach.
    """
    for value in ('not-a-uuid', '', None, 12345, object()):
        assert school_pk_for_uuid(value) is None


@pytest.mark.django_db
def test_an_unknown_uuid_returns_none(db):
    assert school_pk_for_uuid(uuid_module.uuid4()) is None


@pytest.mark.django_db
def test_an_unknown_pk_returns_none(db):
    assert uuid_for_school_pk(9_999_999) is None


# ----------------------------------------------------------------- cache ----

@pytest.mark.django_db
def test_a_hit_costs_no_query(school, django_assert_num_queries):
    school_pk_for_uuid(school.uuid)          # warm
    with django_assert_num_queries(0):
        assert school_pk_for_uuid(school.uuid) == school.pk
        assert uuid_for_school_pk(school.pk) == str(school.uuid)


@pytest.mark.django_db
def test_one_direction_populates_the_other(school, django_assert_num_queries):
    school_pk_for_uuid(school.uuid)
    with django_assert_num_queries(0):
        assert uuid_for_school_pk(school.pk) == str(school.uuid)


@pytest.mark.django_db
def test_misses_are_never_cached(db, django_assert_num_queries):
    """Otherwise a client can grow the dict without bound by sending uuids."""
    before = len(school_cache._pk_by_uuid)
    for _ in range(5):
        school_pk_for_uuid(uuid_module.uuid4())
    assert len(school_cache._pk_by_uuid) == before

    # and a miss must keep querying rather than answering from a negative entry
    missing = uuid_module.uuid4()
    school_pk_for_uuid(missing)
    with django_assert_num_queries(1):
        assert school_pk_for_uuid(missing) is None


@pytest.mark.django_db
def test_a_school_created_after_warmup_is_found(school):
    """The miss path, not the signal, is what makes this correct across workers."""
    school_pk_for_uuid(school.uuid)                      # warm the cache
    later = School.objects.create(slug='school_b', name='B')
    assert school_pk_for_uuid(later.uuid) == later.pk


@pytest.mark.django_db
def test_saving_a_school_clears_the_cache(school):
    school_pk_for_uuid(school.uuid)
    assert school_cache._pk_by_uuid
    school.name = 'Renamed'
    school.save()
    assert not school_cache._pk_by_uuid


@pytest.mark.django_db
def test_deleting_a_school_clears_the_cache(db):
    doomed = SchoolFactory(slug='doomed')
    school_pk_for_uuid(doomed.uuid)
    doomed.delete()
    assert not school_cache._pk_by_uuid


@pytest.mark.django_db
def test_lookups_ignore_is_active(db):
    """A deactivated school must still resolve.

    Falling through to None here would drop the request to UNSET — fail-closed
    by accident, in a way that reads as a scope bug rather than a disabled
    tenant. Refusing the user is the caller's decision.
    """
    dormant = SchoolFactory(slug='dormant', is_active=False)
    assert school_pk_for_uuid(dormant.uuid) == dormant.pk
    assert uuid_for_school_pk(dormant.pk) == str(dormant.uuid)


# -------------------------------------------------------------- managers ----

def test_objects_is_the_default_manager():
    """The trap: Django takes the FIRST declared manager as the default.

    Declaring `visible` without an explicit `objects` above it would make the
    filtered manager the default — which is what forward FKs, the admin and
    migrations resolve through, so deactivated schools would vanish from all of
    them and from every `school` FK on every tenant row.
    """
    assert School._meta.default_manager.name == 'objects'
    assert type(School._meta.default_manager) is models.Manager


def test_school_is_not_scoped_by_itself():
    from core.tenancy import SchoolScopedManagerMixin
    assert not isinstance(School._meta.default_manager, SchoolScopedManagerMixin)


@pytest.mark.django_db
def test_visible_hides_deactivated_schools(school):
    SchoolFactory(slug='dormant', is_active=False)
    assert isinstance(School.visible, SchoolVisibleManager)

    # Relative, not absolute: migration 0037 seeds the two real tenants.
    visible = set(School.visible.values_list('slug', flat=True))
    everything = set(School.objects.values_list('slug', flat=True))
    assert 'dormant' in everything and 'dormant' not in visible
    assert 'school_a' in visible
    assert visible == everything - {'dormant'}
