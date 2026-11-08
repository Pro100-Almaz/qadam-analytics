"""
The teaching assignment inline on the SubjectOffering admin page.

Only the quarter is editable. A new row is added by copying an existing one:
it keeps the source's teacher and role, and the admin picks the quarter.
"""

import pytest
from django.urls import reverse

from apps.home.models import TeachingAssignment
from core.factories import (
    SubjectOfferingFactory, TeacherFactory, TeachingAssignmentFactory, UserFactory,
)


@pytest.fixture
def offering(db):
    return SubjectOfferingFactory()


@pytest.fixture
def admin_client(client, offering):
    # /admin/ is scoped to the superuser's own school, so it is the offering's.
    superuser = UserFactory(
        is_staff=True, is_superuser=True, school=offering.school,
    )
    client.post(
        reverse('admin:login'),
        {'username': superuser.username, 'password': 'testpass123', 'next': '/admin/'},
    )
    return client


@pytest.fixture
def q1_ta(offering):
    return TeachingAssignmentFactory(
        offering=offering, teacher=TeacherFactory(), role='assistant', quarter=1,
    )


def change_url(offering):
    return reverse('admin:home_subjectoffering_change', args=[offering.pk])


def post_offering(client, offering, existing, new=()):
    """POST the change form; `existing` is [(ta, quarter)], `new` a list of row dicts."""
    data = {
        'subject': offering.subject_id,
        'class_group': offering.class_group_id,
        'max_points': offering.max_points,
        'grading_strategy': offering.grading_strategy,
        'teaching_assignments-TOTAL_FORMS': str(len(existing) + len(new)),
        'teaching_assignments-INITIAL_FORMS': str(len(existing)),
        'lessons-TOTAL_FORMS': '0',
        'lessons-INITIAL_FORMS': '0',
    }
    for i, (ta, quarter) in enumerate(existing):
        data[f'teaching_assignments-{i}-id'] = ta.pk
        data[f'teaching_assignments-{i}-offering'] = offering.pk
        data[f'teaching_assignments-{i}-quarter'] = '' if quarter is None else quarter
    for i, row in enumerate(new, start=len(existing)):
        data[f'teaching_assignments-{i}-offering'] = offering.pk
        for key, value in row.items():
            data[f'teaching_assignments-{i}-{key}'] = value
    return client.post(change_url(offering), data)


def inline_errors(response):
    formset = response.context['inline_admin_formsets'][0].formset
    return [form.errors for form in formset.forms], formset.non_form_errors()


@pytest.mark.django_db
def test_change_page_renders_a_copy_button_per_assignment(admin_client, offering, q1_ta):
    response = admin_client.get(change_url(offering))

    html = response.content.decode()
    assert response.status_code == 200
    assert f'class="ta-copy" data-id="{q1_ta.pk}"' in html
    # The JS fills this in on the row the copy adds.
    assert 'name="teaching_assignments-__prefix__-copy_from"' in html


@pytest.mark.django_db
def test_existing_assignment_quarter_is_editable(admin_client, offering, q1_ta):
    response = post_offering(admin_client, offering, [(q1_ta, 3)])

    assert response.status_code == 302
    q1_ta.refresh_from_db()
    assert q1_ta.quarter == 3


@pytest.mark.django_db
def test_copy_creates_assignment_with_source_teacher_and_role(
    admin_client, offering, q1_ta,
):
    response = post_offering(
        admin_client, offering, [(q1_ta, 1)],
        new=[{'copy_from': q1_ta.pk, 'quarter': 2}],
    )

    assert response.status_code == 302
    copy = TeachingAssignment.objects.get(offering=offering, quarter=2)
    assert (copy.teacher_id, copy.role) == (q1_ta.teacher_id, 'assistant')


@pytest.mark.django_db
def test_copy_ignores_posted_teacher_and_role(admin_client, offering, q1_ta):
    other = TeacherFactory()
    response = post_offering(
        admin_client, offering, [(q1_ta, 1)],
        new=[{'copy_from': q1_ta.pk, 'quarter': 2,
              'teacher': other.pk, 'role': 'primary'}],
    )

    assert response.status_code == 302
    copy = TeachingAssignment.objects.get(offering=offering, quarter=2)
    assert (copy.teacher_id, copy.role) == (q1_ta.teacher_id, 'assistant')


@pytest.mark.django_db
def test_copy_into_a_quarter_the_teacher_has_is_refused(admin_client, offering, q1_ta):
    response = post_offering(
        admin_client, offering, [(q1_ta, 1)],
        new=[{'copy_from': q1_ta.pk, 'quarter': 1}],
    )

    assert response.status_code == 200
    errors, _ = inline_errors(response)
    assert 'quarter' in errors[1]
    assert TeachingAssignment.objects.filter(offering=offering).count() == 1


@pytest.mark.django_db
def test_copy_without_a_quarter_is_refused(admin_client, offering, q1_ta):
    response = post_offering(
        admin_client, offering, [(q1_ta, 1)],
        new=[{'copy_from': q1_ta.pk, 'quarter': ''}],
    )

    assert response.status_code == 200
    errors, _ = inline_errors(response)
    assert 'quarter' in errors[1]
    assert TeachingAssignment.objects.filter(offering=offering).count() == 1


@pytest.mark.django_db
def test_new_row_without_copy_source_is_refused(admin_client, offering, q1_ta):
    response = post_offering(
        admin_client, offering, [(q1_ta, 1)], new=[{'quarter': 2}],
    )

    assert response.status_code == 200
    errors, _ = inline_errors(response)
    assert '__all__' in errors[1]
    assert TeachingAssignment.objects.filter(offering=offering).count() == 1


@pytest.mark.django_db
def test_copy_from_another_offerings_assignment_is_refused(
    admin_client, offering, q1_ta,
):
    foreign = TeachingAssignmentFactory(
        offering=SubjectOfferingFactory(class_group=offering.class_group), quarter=1,
    )
    response = post_offering(
        admin_client, offering, [(q1_ta, 1)],
        new=[{'copy_from': foreign.pk, 'quarter': 2}],
    )

    assert response.status_code == 200
    errors, _ = inline_errors(response)
    assert '__all__' in errors[1]
    assert TeachingAssignment.objects.filter(offering=offering).count() == 1


@pytest.mark.django_db
def test_page_with_a_null_quarter_assignment_still_saves(admin_client, offering, q1_ta):
    legacy = TeachingAssignmentFactory(offering=offering, quarter=None)

    response = post_offering(admin_client, offering, [(q1_ta, 2), (legacy, None)])

    assert response.status_code == 302
    q1_ta.refresh_from_db()
    assert q1_ta.quarter == 2
