"""
Spec 0010 — the assignment heatmap endpoints are gone.

Both URLs stop resolving, the `can_heatmap` flag leaves the offering picker,
and the two heatmaps over other data stay. Each test is named after its AC.
"""

import datetime

import pytest
from django.urls import Resolver404, resolve, reverse

from apps.home.models import SubjectAssignment
from core.factories import HomeworkFactory


def mirror(homework):
    return SubjectAssignment.objects.get(category__code='homework', detail_id=homework.pk)


@pytest.mark.parametrize('path', [
    '/api/v1/analytics/offerings/1/assignment-heatmap/',
    '/api/v1/analytics/teacher/offerings/1/assignment-heatmap/',
])
def test_ac1_assignment_heatmap_routes_are_gone(path):
    with pytest.raises(Resolver404):
        resolve(path)


# AC-2 (the `can_heatmap` field of analytics/assignment-offerings/) is
# superseded by spec 0012, which removes that endpoint altogether.


@pytest.mark.parametrize('name', [
    'lesson-api:analytics-topic-heatmap',
    'lesson-api:analytics-attendance-heatmap',
])
def test_ac3_other_heatmaps_still_resolve(name):
    assert resolve(reverse(name, args=[1])).url_name == name.split(':')[1]


def test_ac4_subject_analytics_never_return_drafts_even_to_the_teacher(
    teacher, teaching_assignment, enrollment, student, authenticated_client,
):
    draft = HomeworkFactory(
        teaching_assignment=teaching_assignment, is_active=False,
        due_date=datetime.date(2026, 10, 1),
    )
    published = HomeworkFactory(
        teaching_assignment=teaching_assignment, is_active=True,
        due_date=datetime.date(2026, 10, 2),
    )

    response = authenticated_client(teacher.user).get(reverse(
        'lesson-api:analytics-assignment-trajectory',
        args=[student.id, teaching_assignment.offering_id],
    ))

    assert response.status_code == 200, response.data
    assert [p['id'] for p in response.data['points']] == [mirror(published).pk]
    assert mirror(draft).is_active is False
