"""A new psychological-state template must land in a school.

PsychologicalStateTemplates is a tenant root: NOT NULL `school`, and no parent
FK to derive one from. Its only live creation site did not supply one, so any
state recorded under a name not already in the table raised an IntegrityError
from the not-null constraint — a 500 on a routed endpoint.
"""

import pytest

from apps.authentication.models import PsychologicalStateTemplates
from core.factories import (
    AdminUserFactory, SchoolFactory, StudentFactory, StudentUserFactory,
)


@pytest.fixture
def school(db):
    # The default slug, deliberately: conftest's autouse `_default_scope`
    # enters this school, and these tests go through the API — so data built
    # under a different slug is invisible to the view once scoping is on, and
    # the endpoint answers 404 instead of exercising what the test is about.
    return SchoolFactory()


@pytest.mark.django_db
def test_unknown_state_name_creates_template_in_the_students_school(
    authenticated_client, school,
):
    student = StudentFactory(user=StudentUserFactory(school=school))
    admin = AdminUserFactory(school=school)

    response = authenticated_client(admin).post(
        f'/api/v1/students/{student.pk}/psychological-state/',
        {'state_name': 'Сосредоточен', 'score': 4, 'comment': 'x'},
        format='json',
    )

    assert response.status_code == 201, response.data
    template = PsychologicalStateTemplates.objects.get(name='Сосредоточен')
    assert template.school_id == school.pk


@pytest.mark.django_db
def test_known_state_name_does_not_duplicate_the_template(
    authenticated_client, school,
):
    PsychologicalStateTemplates.objects.create(name='Спокоен', school=school)
    student = StudentFactory(user=StudentUserFactory(school=school))
    admin = AdminUserFactory(school=school)

    response = authenticated_client(admin).post(
        f'/api/v1/students/{student.pk}/psychological-state/',
        {'state_name': 'Спокоен', 'score': 5},
        format='json',
    )

    assert response.status_code == 201, response.data
    assert PsychologicalStateTemplates.objects.filter(name='Спокоен').count() == 1
