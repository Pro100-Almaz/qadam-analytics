"""Achievements and reading entries are paginated (spec 0019)."""
import pytest
from django.urls import reverse

from apps.achievement.models import Achievement, ReadingEntry
from core.factories import AcademicYearFactory, AdminUserFactory


def achievements_url(student, query=''):
    return reverse('achievement-api:achievement-list-create', args=[student.pk]) + query


def readings_url(student, query=''):
    return reverse('achievement-api:reading-entry-list-create', args=[student.pk]) + query


def achievement(student, year, category='olympiad'):
    return Achievement.objects.create(student=student, academic_year=year, category=category)


def reading(student, year, month, title='Book'):
    return ReadingEntry.objects.create(
        student=student, academic_year=year, month=month, title=title,
    )


@pytest.fixture
def client(authenticated_client):
    return authenticated_client(AdminUserFactory())


def test_ac29_achievements_paginated_with_filters(student, academic_year, client):
    older_year = AcademicYearFactory(is_active=False)
    first = achievement(student, academic_year)
    second = achievement(student, academic_year, category='project')
    achievement(student, older_year)

    data = client.get(achievements_url(student)).data
    assert set(data) == {'count', 'next', 'previous', 'results'}
    assert data['count'] == 3

    page = client.get(achievements_url(student, '?page_size=1&page=2')).data
    assert page['count'] == 3 and len(page['results']) == 1
    assert page['next'] and page['previous']

    by_year = client.get(achievements_url(student, f'?year={academic_year.pk}')).data
    assert {r['id'] for r in by_year['results']} == {first.id, second.id}
    by_category = client.get(achievements_url(student, '?category=project')).data
    assert [r['id'] for r in by_category['results']] == [second.id]


def test_ac30_reading_entries_paginated_with_filters(student, academic_year, client):
    older_year = AcademicYearFactory(is_active=False)
    september = reading(student, academic_year, 9, 'A')
    reading(student, academic_year, 10, 'B')
    reading(student, older_year, 9, 'C')

    data = client.get(readings_url(student)).data
    assert set(data) == {'count', 'next', 'previous', 'results'}
    assert data['count'] == 3

    page = client.get(readings_url(student, '?page_size=2&page=2')).data
    assert len(page['results']) == 1 and page['previous']

    filtered = client.get(
        readings_url(student, f'?year={academic_year.pk}&month=9'),
    ).data
    assert [r['id'] for r in filtered['results']] == [september.id]


def test_ac32_default_20_max_100_and_post_unchanged(student, academic_year, client):
    Achievement.objects.bulk_create([
        Achievement(student=student, academic_year=academic_year, category='olympiad')
        for _ in range(105)
    ])

    assert len(client.get(achievements_url(student)).data['results']) == 20
    assert len(client.get(achievements_url(student, '?page_size=500')).data['results']) == 100

    created = client.post(
        achievements_url(student),
        {'academic_year': academic_year.pk, 'category': 'project'},
        format='json',
    )
    assert created.status_code == 201, created.data
    assert created.data['category'] == 'project'
    assert 'results' not in created.data
