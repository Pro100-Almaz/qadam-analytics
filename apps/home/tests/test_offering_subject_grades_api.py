"""
Spec 0009 — GET offerings/<offering_id>/subject-grades/: every assignment of
an offering, each with its grades nested inside.

Visibility must match the per-assignment endpoints exactly, so most of these
tests are about who sees which assignment and which grade. Each test is named
after the AC it pins down.
"""

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment
from core.factories import (
    AdminUserFactory, ClassGroupFactory, EnrollmentFactory, ParentFactory,
    SchoolFactory, SubjectAssignmentFactory, SubjectGradeFactory,
    SubjectOfferingFactory, TeacherFactory, TeachingAssignmentFactory,
)
from core.tenancy import school_scope


def url_for(offering):
    return reverse('home-api:offering-subject-grades', args=[offering.id])


@pytest.fixture
def world(academic_year):
    """
    Maths for 7A, taught by `teacher`, with two enrolled students.

      quiz    2026-09-10  lesson, published, both students graded
      exam    2026-09-20  exam,   published, s1 graded
      draft   2026-09-25  lesson, unpublished, s1 graded

    Plus an assignment in another offering, which must never appear.
    """
    class_group = ClassGroupFactory(academic_year=academic_year)
    offering = SubjectOfferingFactory(class_group=class_group)
    teacher = TeacherFactory()
    TeachingAssignmentFactory(teacher=teacher, offering=offering)

    s1, s2 = (EnrollmentFactory(class_group=class_group).student for _ in range(2))
    s1.user.last_name, s2.user.last_name = 'Bekov', 'Abenov'
    s1.user.save()
    s2.user.save()

    quiz = SubjectAssignmentFactory(
        offering=offering, title='quiz', date=datetime.date(2026, 9, 10),
    )
    exam = SubjectAssignmentFactory(
        offering=offering, title='exam', category='exam',
        date=datetime.date(2026, 9, 20),
    )
    draft = SubjectAssignmentFactory(
        offering=offering, title='draft', is_active=False,
        date=datetime.date(2026, 9, 25),
    )
    SubjectGradeFactory(assignment=quiz, student=s1, grade=80, comments='good')
    SubjectGradeFactory(assignment=quiz, student=s2, grade=60)
    SubjectGradeFactory(assignment=exam, student=s1, grade=90)
    SubjectGradeFactory(assignment=draft, student=s1, grade=70)

    SubjectAssignmentFactory(title='elsewhere')

    return {
        'offering': offering, 'class_group': class_group, 'teacher': teacher,
        's1': s1, 's2': s2,
    }


def by_title(response):
    """{assignment title: [(student id, grade), ...]} in response order."""
    return {
        row['title']: [(g['student'], g['grade']) for g in row['grades']]
        for row in response.data['results']
    }


def test_ac1_teacher_gets_every_assignment_with_nested_grades(world, authenticated_client):
    response = authenticated_client(world['teacher'].user).get(url_for(world['offering']))

    assert response.status_code == 200
    s1, s2 = world['s1'], world['s2']
    assert by_title(response) == {
        'draft': [(s1.id, 70)],
        'exam': [(s1.id, 90)],
        'quiz': [(s2.id, 60), (s1.id, 80)],
    }

    quiz = next(r for r in response.data['results'] if r['title'] == 'quiz')
    assert quiz['offering_id'] == world['offering'].id
    assert set(quiz) >= {
        'id', 'title', 'category', 'category_name', 'max_grade', 'date',
        'is_active', 'subject_name', 'class_group_name', 'grades',
    }
    assert set(quiz['grades'][1]) == {
        'id', 'student', 'student_user_id', 'student_name',
        'grade', 'comments', 'created_at',
    }
    assert quiz['grades'][1]['comments'] == 'good'
    assert quiz['grades'][1]['student_user_id'] == s1.user_id


def test_ac2_other_offerings_assignments_never_appear(world, authenticated_client):
    response = authenticated_client(AdminUserFactory()).get(url_for(world['offering']))

    assert 'elsewhere' not in by_title(response)
    assert set(by_title(response)) == {'quiz', 'exam', 'draft'}


def test_ac3_student_sees_published_assignments_and_only_own_grade(
    world, authenticated_client,
):
    response = authenticated_client(world['s2'].user).get(url_for(world['offering']))

    assert response.status_code == 200
    assert by_title(response) == {'exam': [], 'quiz': [(world['s2'].id, 60)]}


def test_ac3_parent_sees_only_their_childs_grades(world, authenticated_client):
    parent = ParentFactory()
    parent.students.add(world['s1'])

    response = authenticated_client(parent.user).get(url_for(world['offering']))

    assert by_title(response) == {
        'exam': [(world['s1'].id, 90)], 'quiz': [(world['s1'].id, 80)],
    }


def test_ac4_unrelated_teacher_gets_empty_list(world, authenticated_client):
    response = authenticated_client(TeacherFactory().user).get(url_for(world['offering']))

    assert response.status_code == 200
    assert response.data['results'] == []


def test_ac5_homeroom_teacher_sees_published_assignments_of_their_class(
    world, authenticated_client,
):
    homeroom = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(
        teacher=homeroom, class_group=world['class_group'],
    )

    response = authenticated_client(homeroom.user).get(url_for(world['offering']))

    s1, s2 = world['s1'], world['s2']
    assert by_title(response) == {
        'exam': [(s1.id, 90)], 'quiz': [(s2.id, 60), (s1.id, 80)],
    }


@pytest.mark.parametrize('params, expected', [
    ({'category': 'exam'}, {'exam'}),
    ({'date': '2026-09-10'}, {'quiz'}),
    ({'date_from': '2026-09-15'}, {'exam', 'draft'}),
    ({'date_to': '2026-09-20'}, {'quiz', 'exam'}),
])
def test_ac6_assignment_filters(world, authenticated_client, params, expected):
    client = authenticated_client(world['teacher'].user)
    response = client.get(url_for(world['offering']), params)

    assert set(by_title(response)) == expected


def test_ac7_newest_first_and_paginated_over_assignments(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)

    full = client.get(url_for(world['offering']))
    assert [r['title'] for r in full.data['results']] == ['draft', 'exam', 'quiz']

    page = client.get(url_for(world['offering']), {'page_size': 2, 'page': 2})
    assert page.data['count'] == 3
    assert [r['title'] for r in page.data['results']] == ['quiz']
    assert len(page.data['results'][0]['grades']) == 2


def test_ac8_missing_offering_is_404(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)
    url = reverse('home-api:offering-subject-grades', args=[999999])

    assert client.get(url).status_code == 404


def test_ac8_other_schools_offering_is_404(world, authenticated_client, settings):
    settings.SCHOOL_SCOPE_MODE = 'enforce'
    with school_scope(SchoolFactory(slug='school_b')):
        foreign = SubjectOfferingFactory()

    assert authenticated_client(AdminUserFactory()).get(url_for(foreign)).status_code == 404


def test_ac8_anonymous_is_401(world, api_client):
    assert api_client.get(url_for(world['offering'])).status_code == 401


def test_ac9_query_count_does_not_grow_with_assignments(world, authenticated_client):
    client = authenticated_client(world['teacher'].user)

    with CaptureQueriesContext(connection) as before:
        client.get(url_for(world['offering']))

    for _ in range(5):
        extra = SubjectAssignmentFactory(offering=world['offering'])
        SubjectGradeFactory(assignment=extra, student=world['s1'], grade=50)
        SubjectGradeFactory(assignment=extra, student=world['s2'], grade=50)

    with CaptureQueriesContext(connection) as after:
        response = client.get(url_for(world['offering']))

    assert response.data['count'] == 8
    assert len(after.captured_queries) == len(before.captured_queries)
