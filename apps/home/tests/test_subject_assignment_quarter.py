"""
Spec 0011 — SubjectAssignment.quarter: stored on the row, derived from the
date when the client does not send one, and filterable on every assignment
and subject-grade list. Each test is named after the AC it pins down.
"""

import datetime
import importlib

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment, SubjectAssignment
from core.factories import (
    ClassGroupFactory, HomeworkFactory, SubjectAssignmentFactory,
    SubjectGradeFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory, EnrollmentFactory,
)

ASSIGNMENTS_URL = reverse('home-api:subject-assignment-list-create')
GRADES_URL = reverse('home-api:subject-grade-list')

D = datetime.date


def detail_url(assignment):
    return reverse('home-api:subject-assignment-detail', args=[assignment.pk])


@pytest.fixture
def year(academic_year):
    academic_year.q1_start, academic_year.q1_end = D(2026, 9, 1), D(2026, 10, 31)
    academic_year.q2_start, academic_year.q2_end = D(2026, 11, 10), D(2026, 12, 28)
    academic_year.q3_start, academic_year.q3_end = D(2027, 1, 8), D(2027, 3, 20)
    academic_year.q4_start, academic_year.q4_end = D(2027, 4, 1), D(2027, 5, 25)
    academic_year.save()
    return academic_year


@pytest.fixture
def world(year):
    class_group = ClassGroupFactory(academic_year=year)
    offering = SubjectOfferingFactory(class_group=class_group)
    teaching_assignment = TeachingAssignmentFactory(offering=offering)
    student = EnrollmentFactory(class_group=class_group).student
    return {
        'offering': offering,
        'teaching_assignment': teaching_assignment,
        'teacher': teaching_assignment.teacher,
        'student': student,
    }


def create(client, offering, **body):
    payload = {
        'offering': offering.id, 'title': 'Quiz', 'max_grade': 10,
        'date': '2026-09-15', **body,
    }
    return client.post(ASSIGNMENTS_URL, payload, format='json')


def test_ac1_response_carries_quarter(world, authenticated_client):
    assignment = SubjectAssignmentFactory(offering=world['offering'], date=D(2026, 11, 20))
    response = authenticated_client(world['teacher'].user).get(detail_url(assignment))

    assert response.status_code == 200
    assert response.data['quarter'] == 2


def test_ac2_quarter_is_derived_from_date_when_omitted(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)

    inside = create(client, world['offering'], date='2027-02-01')
    between = create(client, world['offering'], date='2026-11-05')

    assert inside.status_code == 201, inside.data
    assert inside.data['quarter'] == 3
    assert between.status_code == 201, between.data
    assert between.data['quarter'] is None


def test_ac3_explicit_quarter_overrides_the_date(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)

    plain = create(client, world['offering'], date='2026-11-05', quarter=1)
    homework = create(
        client, world['offering'], category='homework', date='2026-09-15', quarter=2,
    )

    assert plain.status_code == 201, plain.data
    assert plain.data['quarter'] == 1
    assert homework.status_code == 201, homework.data
    assert homework.data['quarter'] == 2
    assert SubjectAssignment.objects.get(pk=homework.data['id']).quarter == 2


@pytest.mark.parametrize('quarter', [0, 5, 'two'])
def test_ac6_quarter_outside_1_to_4_is_rejected_on_write(world, authenticated_client, quarter):
    response = create(authenticated_client(world['teacher'].user), world['offering'], quarter=quarter)

    assert response.status_code == 400
    assert 'quarter' in response.data


def test_ac4_patch_date_rederives_patch_quarter_sets_it(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)
    assignment = SubjectAssignmentFactory(offering=world['offering'], date=D(2026, 9, 15))
    assert assignment.quarter == 1

    moved = client.patch(detail_url(assignment), {'date': '2027-04-10'}, format='json')
    assert moved.status_code == 200, moved.data
    assert moved.data['quarter'] == 4

    set_ = client.patch(detail_url(assignment), {'quarter': 3}, format='json')
    assert set_.status_code == 200, set_.data
    assert set_.data['quarter'] == 3

    both = client.patch(
        detail_url(assignment), {'date': '2026-09-20', 'quarter': 2}, format='json',
    )
    assert both.status_code == 200, both.data
    assert both.data['quarter'] == 2


def test_ac7_homework_due_date_change_rederives_mirror_quarter(world):
    homework = HomeworkFactory(
        teaching_assignment=world['teaching_assignment'], due_date=D(2026, 9, 15),
    )
    mirror = SubjectAssignment.objects.get(detail_id=homework.pk, category__code='homework')
    assert mirror.quarter == 1

    homework.due_date = D(2026, 12, 1)
    homework.save()
    mirror.refresh_from_db()
    assert mirror.quarter == 2

    # Any other edit keeps a quarter set on the assignment by hand.
    mirror.quarter = 3
    mirror.save(sync=False)
    homework.description = 'renamed'
    homework.save()
    mirror.refresh_from_db()
    assert mirror.quarter == 3


@pytest.fixture
def quartered(world):
    """One graded assignment in Q1, one in Q2, one with no quarter."""
    rows = {}
    for title, day in [('q1', D(2026, 9, 15)), ('q2', D(2026, 12, 1)), ('none', D(2026, 11, 5))]:
        rows[title] = SubjectAssignmentFactory(offering=world['offering'], title=title, date=day)
        SubjectGradeFactory(assignment=rows[title], student=world['student'], grade=5)
    assert rows['none'].quarter is None
    return rows


@pytest.mark.parametrize('url_name', [
    'subject-assignment-list-create',
    'offering-subject-grades',
])
def test_ac5_quarter_filters_assignment_lists(world, quartered, authenticated_client, url_name):
    args = [world['offering'].id] if url_name == 'offering-subject-grades' else []
    url = reverse(f'home-api:{url_name}', args=args)
    client = authenticated_client(world['teacher'].user)

    response = client.get(url, {'quarter': 2})

    assert response.status_code == 200
    assert [row['title'] for row in response.data['results']] == ['q2']
    assert len(client.get(url).data['results']) == 3


def test_ac5_quarter_filters_subject_grades(world, quartered, authenticated_client):
    response = authenticated_client(world['teacher'].user).get(GRADES_URL, {'quarter': 1})

    assert response.status_code == 200
    assert [row['assignment']['title'] for row in response.data['results']] == ['q1']


def test_ac5_quarter_filters_homeroom_lists(world, quartered, authenticated_client):
    homeroom_teacher = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(
        teacher=homeroom_teacher, class_group=world['offering'].class_group,
    )
    client = authenticated_client(homeroom_teacher.user)

    assignments = client.get(
        reverse('home-api:homeroom-subject-assignment-list'), {'quarter': 1},
    )
    grades = client.get(reverse('home-api:homeroom-subject-grade-list'), {'quarter': 2})

    assert assignments.status_code == 200
    assert [row['title'] for row in assignments.data['results']] == ['q1']
    assert grades.status_code == 200
    assert [row['assignment']['title'] for row in grades.data['results']] == ['q2']


@pytest.mark.parametrize('value', ['0', '5', 'x'])
def test_ac6_invalid_quarter_filter_is_400(world, authenticated_client, value):
    client = authenticated_client(world['teacher'].user)

    assert client.get(ASSIGNMENTS_URL, {'quarter': value}).status_code == 400
    assert client.get(GRADES_URL, {'quarter': value}).status_code == 400


def test_ac8_migration_backfills_quarter_from_date(world):
    assignment = SubjectAssignmentFactory(offering=world['offering'], date=D(2027, 2, 1))
    outside = SubjectAssignmentFactory(offering=world['offering'], date=D(2027, 7, 1))
    SubjectAssignment.objects.filter(pk=assignment.pk).update(quarter=None)

    migration = importlib.import_module('apps.home.migrations.0045_subjectassignment_quarter')
    migration.backfill_quarter(django_apps, None)

    assignment.refresh_from_db()
    outside.refresh_from_db()
    assert assignment.quarter == 3
    assert outside.quarter is None


def test_teacher_without_offering_sees_nothing_in_any_quarter(world, quartered, authenticated_client):
    stranger = TeacherFactory()
    response = authenticated_client(stranger.user).get(ASSIGNMENTS_URL, {'quarter': 1})

    assert response.status_code == 200
    assert response.data['results'] == []
