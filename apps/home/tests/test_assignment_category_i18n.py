"""
Spec 0006 — assignment category names in en / ru / kk, picked by Accept-Language.

AC-1 … AC-7. The language comes from LocaleMiddleware; the per-language columns
from django-modeltranslation (apps/home/translation.py).
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import translation

from apps.home.models import AssignmentCategory
from core.factories import (
    AssignmentCategoryFactory, SchoolFactory, SubjectAssignmentFactory, UserFactory,
)

CATEGORIES_URL = reverse('home-api:assignment-category-list')
ASSIGNMENTS_URL = reverse('home-api:subject-assignment-list-create')


@pytest.fixture(autouse=True)
def _reset_language():
    """LocaleMiddleware activates a language per request; don't let it leak."""
    yield
    translation.deactivate()


@pytest.fixture
def superuser(db):
    return UserFactory(is_staff=True, is_superuser=True, school=SchoolFactory())


@pytest.fixture
def admin_client(client, superuser):
    client.post(
        reverse('admin:login'),
        {'username': superuser.username, 'password': 'testpass123', 'next': '/admin/'},
    )
    return client


@pytest.fixture
def api(teacher, authenticated_client):
    return authenticated_client(teacher.user)


def names(response):
    return {row['code']: row['name'] for row in response.data}


def test_ac1_admin_must_enter_every_language(admin_client):
    for missing in ('name_en', 'name_ru', 'name_kk'):
        data = {'code': 'project', 'name_en': 'Project', 'name_ru': 'Проект', 'name_kk': 'Жоба'}
        data[missing] = ''

        response = admin_client.post(reverse('admin:home_assignmentcategory_add'), data)

        assert response.status_code == 200, missing
        assert response.context['adminform'].form.errors, missing
        assert not AssignmentCategory.objects.filter(code='project').exists()

    response = admin_client.post(reverse('admin:home_assignmentcategory_add'), {
        'code': 'project', 'name_en': 'Project', 'name_ru': 'Проект', 'name_kk': 'Жоба',
    })
    assert response.status_code == 302
    category = AssignmentCategory.objects.get(code='project')
    assert (category.name_en, category.name_ru, category.name_kk) == ('Project', 'Проект', 'Жоба')


@pytest.mark.parametrize('language, expected', [
    ('en', 'Exam'),
    ('ru', 'Экзамен'),
    ('kk', 'Емтихан'),
])
def test_ac2_name_follows_accept_language(api, language, expected):
    AssignmentCategoryFactory(code='exam')

    response = api.get(CATEGORIES_URL, HTTP_ACCEPT_LANGUAGE=language)

    assert response.status_code == 200
    assert names(response)['exam'] == expected
    assert response['Content-Language'] == language


@pytest.mark.parametrize('headers', [{}, {'HTTP_ACCEPT_LANGUAGE': 'de'}])
def test_ac3_missing_or_unsupported_language_falls_back_to_english(api, headers):
    AssignmentCategoryFactory(code='homework')

    response = api.get(CATEGORIES_URL, **headers)

    assert names(response)['homework'] == 'Homework'
    assert response['Content-Language'] == 'en'


@pytest.mark.parametrize('header, expected', [
    ('ru-RU', 'Домашнее задание'),
    ('kk-KZ,kk;q=0.9,en;q=0.8', 'Үй жұмысы'),
])
def test_ac4_regional_and_weighted_headers_resolve(api, header, expected):
    AssignmentCategoryFactory(code='homework')

    response = api.get(CATEGORIES_URL, HTTP_ACCEPT_LANGUAGE=header)

    assert names(response)['homework'] == expected


def test_ac5_seeded_categories_have_every_language(db):
    for code, expected in AssignmentCategory.BUILTIN_NAMES.items():
        category = AssignmentCategory.builtin(code)
        assert {
            'name_en': category.name_en,
            'name_ru': category.name_ru,
            'name_kk': category.name_kk,
        } == expected


def test_ac6_category_name_on_assignments_follows_accept_language(
    api, teaching_assignment,
):
    SubjectAssignmentFactory(offering=teaching_assignment.offering, category='final')

    response = api.get(ASSIGNMENTS_URL, HTTP_ACCEPT_LANGUAGE='kk')

    row, = response.data['results']
    assert row['category'] == 'final'
    assert row['category_name'] == 'Қорытынды жұмыс'


def test_ac7_response_shape_is_unchanged(api):
    AssignmentCategoryFactory(code='lesson')

    response = api.get(CATEGORIES_URL, HTTP_ACCEPT_LANGUAGE='ru')

    for row in response.data:
        assert set(row) == {'id', 'code', 'name'}
        assert isinstance(row['name'], str)


# ── Migration (AC-5) ──

BEFORE = [('home', '0043_assignment_category_fk')]
AFTER = [('home', '0044_assignment_category_translations')]


@pytest.fixture
def migrate_to(transactional_db):
    executor = MigrationExecutor(connection)

    def _migrate(targets):
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    yield _migrate

    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_ac5_migration_keeps_existing_names_as_english(migrate_to):
    old_apps = migrate_to(BEFORE)
    OldCategory = old_apps.get_model('home', 'AssignmentCategory')
    OldCategory.objects.create(code='project', name='Project')
    OldCategory.objects.get_or_create(code='exam', defaults={'name': 'Exam'})

    new_apps = migrate_to(AFTER)
    Category = new_apps.get_model('home', 'AssignmentCategory')

    project = Category.objects.get(code='project')
    assert (project.name_en, project.name_ru, project.name_kk) == ('Project', None, None)
    exam = Category.objects.get(code='exam')
    assert (exam.name_en, exam.name_ru, exam.name_kk) == ('Exam', 'Экзамен', 'Емтихан')
