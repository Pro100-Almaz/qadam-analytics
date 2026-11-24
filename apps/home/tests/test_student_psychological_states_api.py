"""GET students/<student_pk>/psychological-states/ (spec 0019)."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import PsychologicalState
from core.factories import (
    AdminUserFactory, ParentFactory, StudentFactory, TeacherFactory, UserFactory,
)


def url(student, query=''):
    return reverse('home-api:student-psychological-states', args=[student.pk]) + query


def state(student, name, score, days_ago, comment=''):
    s = PsychologicalState.objects.create(
        student=student, name=name, score=score, comment=comment,
    )
    PsychologicalState.objects.filter(pk=s.pk).update(
        time_added=timezone.now() - timedelta(days=days_ago),
    )
    return s


@pytest.fixture
def history(db):
    student = StudentFactory()
    states = [
        state(student, 'Mood', 4, 10),
        state(student, 'Sleep', 2, 5, comment='tired'),
        state(student, 'Mood', 3, 1),
    ]
    return student, states


def test_ac24_psych_states_paginated_newest_first(history, authenticated_client):
    student, (mood_old, sleep, mood_new) = history

    data = authenticated_client(AdminUserFactory()).get(url(student)).data

    assert set(data) == {'count', 'next', 'previous', 'results'}
    assert data['count'] == 3
    assert [r['id'] for r in data['results']] == [mood_new.id, sleep.id, mood_old.id]
    assert set(data['results'][0]) == {
        'id', 'name', 'score', 'comment', 'added_by', 'time_added',
    }
    assert data['results'][1]['comment'] == 'tired'


def test_ac25_psych_states_name_filter(history, authenticated_client):
    student, (mood_old, _, mood_new) = history

    data = authenticated_client(AdminUserFactory()).get(url(student, '?name=Mood')).data

    assert [r['id'] for r in data['results']] == [mood_new.id, mood_old.id]


def test_ac26_psych_states_page_size_capped_at_100(history, authenticated_client):
    student, (_, sleep, mood_new) = history
    for i in range(101):
        state(student, 'Focus', 3, 20 + i)
    client = authenticated_client(AdminUserFactory())

    page2 = client.get(url(student, '?page=2&page_size=1')).data
    assert [r['id'] for r in page2['results']] == [sleep.id]
    assert page2['next'] and page2['previous']

    assert len(client.get(url(student, '?page_size=500')).data['results']) == 100
    assert len(client.get(url(student)).data['results']) == 20


def test_ac27_psych_states_permissions_match_detail(history, authenticated_client):
    student, _ = history
    parent = ParentFactory()
    parent.students.add(student)
    stranger_parent = ParentFactory()

    for user, expected in [
        (AdminUserFactory(), 200),
        (TeacherFactory().user, 200),          # can_view_student: any teacher
        (UserFactory(group_name='Psychologist'), 200),
        (student.user, 200),
        (parent.user, 200),
        (stranger_parent.user, 403),
        (StudentFactory().user, 403),
    ]:
        response = authenticated_client(user).get(url(student))
        assert response.status_code == expected, (user.groups.first(), response.data)


def test_ac28_detail_still_embeds_current_and_history(history, authenticated_client):
    student, (mood_old, sleep, mood_new) = history

    response = authenticated_client(AdminUserFactory()).get(
        reverse('home-api:student-detail', args=[student.user_id]),
    )

    embedded = response.data['psychological_states']
    assert [r['id'] for r in embedded['current']] == [mood_new.id, sleep.id]
    assert [r['id'] for r in embedded['history']['Mood']] == [mood_old.id, mood_new.id]
    assert embedded['history']['Sleep'][0] == {
        'id': sleep.id, 'name': 'Sleep', 'score': 2, 'comment': 'tired',
        'added_by': '', 'time_added': embedded['history']['Sleep'][0]['time_added'],
    }
