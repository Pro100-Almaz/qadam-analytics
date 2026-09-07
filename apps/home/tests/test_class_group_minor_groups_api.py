"""GET /api/v1/class-groups/<id>/minor-groups/ — the подгруппы of one class."""

import pytest
from django.urls import reverse

from apps.home.models import ClassGroup, ClassGroupCollection
from core.factories import (
    AdminUserFactory, ClassGroupFactory, MinorClassGroupFactory,
)


def url_for(class_group_id):
    return reverse('home-api:class-group-minor-groups', args=[class_group_id])


@pytest.fixture
def major_a(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='A')


@pytest.fixture
def major_b(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='B')


@pytest.fixture
def admin_api_client(db, authenticated_client):
    return authenticated_client(AdminUserFactory())


def test_returns_the_subgroups_bound_to_the_class(admin_api_client, major_a, academic_year):
    english = MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')
    chess = MinorClassGroupFactory(academic_year=academic_year, letter='Шахматы')
    ClassGroupCollection.bind_minor_groups(major_a, [english, chess])

    response = admin_api_client.get(url_for(major_a.id))

    assert response.status_code == 200
    assert {group['id'] for group in response.data} == {english.id, chess.id}


def test_payload_carries_the_minor_category_and_display_name(
    admin_api_client, major_a, academic_year
):
    english = MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')
    ClassGroupCollection.bind_minor_groups(major_a, [english])

    payload = admin_api_client.get(url_for(major_a.id)).data[0]

    assert payload['id'] == english.id
    assert payload['letter'] == 'English Advanced'
    assert payload['category'] == ClassGroup.MINOR_CHOICE
    assert payload['display_name'] == str(english)
    assert payload['grade_level'] is None


def test_a_shared_subgroup_is_returned_for_every_class_holding_it(
    admin_api_client, major_a, major_b, academic_year
):
    english = MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')
    ClassGroupCollection.bind_minor_groups(major_a, [english])
    ClassGroupCollection.bind_minor_groups(major_b, [english])

    assert [g['id'] for g in admin_api_client.get(url_for(major_a.id)).data] == [english.id]
    assert [g['id'] for g in admin_api_client.get(url_for(major_b.id)).data] == [english.id]


def test_another_class_subgroups_are_left_out(admin_api_client, major_a, major_b, academic_year):
    chess = MinorClassGroupFactory(academic_year=academic_year, letter='Шахматы')
    ClassGroupCollection.bind_minor_groups(major_b, [chess])

    assert admin_api_client.get(url_for(major_a.id)).data == []


def test_a_class_without_a_constellation_returns_an_empty_list(admin_api_client, major_a):
    response = admin_api_client.get(url_for(major_a.id))

    assert response.status_code == 200
    assert response.data == []


def test_a_subgroup_id_returns_an_empty_list(admin_api_client, academic_year):
    chess = MinorClassGroupFactory(academic_year=academic_year, letter='Шахматы')

    response = admin_api_client.get(url_for(chess.id))

    assert response.status_code == 200
    assert response.data == []


def test_unknown_class_group_is_a_404(admin_api_client):
    assert admin_api_client.get(url_for(9999)).status_code == 404


def test_anonymous_access_is_rejected(api_client, major_a):
    assert api_client.get(url_for(major_a.id)).status_code == 401
