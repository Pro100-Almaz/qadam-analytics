"""The admin shows the parent-child link from both ends.

ParentAdmin lists each parent's children (with their class) on the changelist
and in a table on the change form; StudentAdmin names the student's parents.
"""

import pytest
from django.contrib import admin as django_admin
from django.urls import reverse

from apps.authentication.models import Parent, Student
from core.factories import (
    ClassGroupFactory, EnrollmentFactory, ParentFactory, StudentFactory,
)


@pytest.fixture
def parent_admin():
    return django_admin.site._registry[Parent]


@pytest.fixture
def student_admin():
    return django_admin.site._registry[Student]


@pytest.fixture
def family(db):
    student = StudentFactory(
        user__first_name='Aru', user__last_name='Child', user__email='aru@test.kz')
    class_group = ClassGroupFactory(letter='B')
    EnrollmentFactory(student=student, class_group=class_group)
    parent = ParentFactory(
        user__first_name='Dana', user__last_name='Parent', user__phone_number='+77001112233')
    parent.students.add(student)
    return parent, student, class_group


def _prefetched(parent_admin, rf, parent):
    request = rf.get('/admin/authentication/parent/')
    return parent_admin.get_queryset(request).get(pk=parent.pk)


@pytest.mark.django_db
def test_parent_list_shows_children_with_class(parent_admin, rf, family):
    parent, student, class_group = family
    html = parent_admin.children(_prefetched(parent_admin, rf, parent))

    assert 'Aru Child' in html
    assert f'({class_group.short_name})' in html
    assert reverse('admin:authentication_student_change', args=[student.pk]) in html


@pytest.mark.django_db
def test_parent_list_children_does_not_query_per_child(
        parent_admin, rf, family, django_assert_num_queries):
    parent, _, _ = family
    obj = _prefetched(parent_admin, rf, parent)

    with django_assert_num_queries(0):
        parent_admin.children(obj)


@pytest.mark.django_db
def test_parent_detail_shows_children_table(parent_admin, rf, family):
    parent, _, class_group = family
    html = parent_admin.children_info(_prefetched(parent_admin, rf, parent))

    assert '<table>' in html
    assert 'Aru Child' in html
    assert class_group.short_name in html
    assert 'aru@test.kz' in html


@pytest.mark.django_db
def test_parent_without_children_shows_dash(parent_admin, rf, db):
    parent = ParentFactory()
    obj = _prefetched(parent_admin, rf, parent)

    assert parent_admin.children_info(obj) == '—'
    assert parent_admin.children_info(None) == '—'


@pytest.mark.django_db
def test_student_detail_shows_parent_names(student_admin, family):
    parent, student, _ = family
    html = student_admin.parents_info(student)

    assert 'Dana Parent' in html
    assert '+77001112233' in html
    assert reverse('admin:authentication_parent_change', args=[parent.pk]) in html


@pytest.mark.django_db
def test_student_without_parents_shows_dash(student_admin, db):
    assert student_admin.parents_info(StudentFactory()) == '—'
    assert student_admin.parents_info(None) == '—'
