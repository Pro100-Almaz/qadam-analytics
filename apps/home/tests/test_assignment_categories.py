"""
Spec 0005 — admin-managed assignment categories and the `detail_id` checks.

AC-1 … AC-11. The Homework <-> SubjectAssignment sync itself is covered in
apps/lesson/tests/test_homework_assignment_sync.py, the migration in
apps/lesson/tests/test_homework_assignment_migration.py.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse

from apps.home.models import AssignmentCategory, SubjectAssignment
from core.factories import (
    AssignmentCategoryFactory, HomeworkFactory, SchoolFactory,
    SubjectAssignmentFactory, TeacherFactory, UserFactory,
)
from core.tenancy import school_scope

CATEGORIES_URL = reverse('home-api:assignment-category-list')
ASSIGNMENTS_URL = reverse('home-api:subject-assignment-list-create')


def detail_url(assignment):
    return reverse('home-api:subject-assignment-detail', args=[assignment.pk])


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


def homework_category():
    return AssignmentCategoryFactory(code=AssignmentCategory.HOMEWORK)


# ── Categories ──

def test_ac1_admin_added_category_is_shared_by_every_school(
    admin_client, teacher, teaching_assignment, authenticated_client,
):
    response = admin_client.post(
        reverse('admin:home_assignmentcategory_add'),
        {'code': 'project', 'name': 'Project'},
    )
    assert response.status_code == 302
    assert AssignmentCategory.objects.filter(code='project').exists()

    with school_scope(SchoolFactory(slug='school_b')):
        teacher_b = TeacherFactory()
    assert teacher_b.user.school_id != teacher.user.school_id

    for user in (teacher.user, teacher_b.user):
        codes = [row['code'] for row in authenticated_client(user).get(CATEGORIES_URL).data]
        assert 'project' in codes

    response = authenticated_client(teacher.user).post(ASSIGNMENTS_URL, {
        'offering': teaching_assignment.offering_id, 'title': 'Poster',
        'max_grade': 20, 'date': '2026-10-01', 'category': 'project',
    }, format='json')
    assert response.status_code == 201, response.data
    assert response.data['category'] == 'project'
    assert response.data['category_name'] == 'Project'


def test_ac2_category_in_use_cannot_be_deleted(admin_client):
    assignment = SubjectAssignmentFactory(category='exam')

    response = admin_client.post(
        reverse('admin:home_assignmentcategory_delete', args=[assignment.category_id]),
        {'post': 'yes'},
    )

    # Django's "cannot delete, these rows are protected" page, not a redirect.
    assert response.status_code == 200
    assert AssignmentCategory.objects.filter(code='exam').exists()
    with pytest.raises(ProtectedError):
        with transaction.atomic():
            assignment.category.delete()


def test_ac2_unused_category_can_be_deleted(admin_client):
    category = AssignmentCategoryFactory(code='quiz')

    response = admin_client.post(
        reverse('admin:home_assignmentcategory_delete', args=[category.pk]),
        {'post': 'yes'},
    )

    assert response.status_code == 302
    assert not AssignmentCategory.objects.filter(code='quiz').exists()


def test_ac3_homework_category_cannot_be_deleted_or_recoded(admin_client):
    category = homework_category()
    assert category.assignments.count() == 0

    response = admin_client.post(
        reverse('admin:home_assignmentcategory_delete', args=[category.pk]),
        {'post': 'yes'},
    )
    assert response.status_code == 403

    admin_client.post(reverse('admin:home_assignmentcategory_changelist'), {
        'action': 'delete_selected', '_selected_action': [category.pk], 'post': 'yes',
    })
    assert AssignmentCategory.objects.filter(pk=category.pk).exists()

    admin_client.post(
        reverse('admin:home_assignmentcategory_change', args=[category.pk]),
        {'code': 'chores', 'name': 'Homework tasks'},
    )
    category.refresh_from_db()
    assert category.code == AssignmentCategory.HOMEWORK
    assert category.name == 'Homework tasks'


def test_ac5_category_is_a_code_on_the_wire_and_filters_by_code(
    teacher, teaching_assignment, authenticated_client,
):
    offering = teaching_assignment.offering
    SubjectAssignmentFactory(offering=offering, category='exam', title='Exam')
    SubjectAssignmentFactory(offering=offering, category='lesson', title='Lesson')
    client = authenticated_client(teacher.user)

    response = client.get(ASSIGNMENTS_URL, {'category': 'exam'})

    assert response.status_code == 200
    rows = response.data['results']
    assert [row['title'] for row in rows] == ['Exam']
    assert rows[0]['category'] == 'exam'


def test_ac5_create_defaults_to_lesson(teacher, teaching_assignment, authenticated_client):
    response = authenticated_client(teacher.user).post(ASSIGNMENTS_URL, {
        'offering': teaching_assignment.offering_id, 'title': 'Classwork',
        'max_grade': 10, 'date': '2026-10-01',
    }, format='json')

    assert response.status_code == 201, response.data
    assert response.data['category'] == 'lesson'


def test_ac5_unknown_category_code_is_a_400(teacher, teaching_assignment, authenticated_client):
    response = authenticated_client(teacher.user).post(ASSIGNMENTS_URL, {
        'offering': teaching_assignment.offering_id, 'title': 'Classwork',
        'max_grade': 10, 'date': '2026-10-01', 'category': 'nope',
    }, format='json')

    assert response.status_code == 400
    assert 'category' in response.data


# ── detail_id checks ──

def test_ac6_homework_assignment_requires_detail_id(offering):
    with pytest.raises(ValidationError) as exc:
        SubjectAssignment.objects.create(
            offering=offering, category=homework_category(),
            title='x', max_grade=10, date='2026-10-01',
        )
    assert 'detail_id' in exc.value.message_dict


def test_ac7_homework_assignment_detail_must_exist(offering):
    with pytest.raises(ValidationError) as exc:
        SubjectAssignment.objects.create(
            offering=offering, category=homework_category(), detail_id=987654,
            title='x', max_grade=10, date='2026-10-01',
        )
    assert 'does not exist' in exc.value.message_dict['detail_id'][0]


def test_ac8_homework_assignment_detail_must_share_the_offering(offering):
    homework = HomeworkFactory()
    assert homework.offering_id != offering.pk

    with pytest.raises(ValidationError) as exc:
        SubjectAssignment.objects.create(
            offering=offering, category=homework_category(), detail_id=homework.pk,
            title='x', max_grade=10, date='2026-10-01',
        )
    assert 'another subject offering' in exc.value.message_dict['detail_id'][0]


def test_ac9_plain_category_forbids_detail_id(offering):
    with pytest.raises(ValidationError) as exc:
        SubjectAssignmentFactory(offering=offering, category='exam', detail_id=1)
    assert 'detail_id' in exc.value.message_dict


def test_ac10_one_assignment_per_detail_row(db):
    homework = HomeworkFactory()
    mirror = SubjectAssignment.objects.get(category__code='homework', detail_id=homework.pk)

    # bulk_create skips save(), so this reaches the database constraint.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubjectAssignment.objects.bulk_create([SubjectAssignment(
                offering_id=mirror.offering_id, category=mirror.category,
                detail_id=homework.pk, title='dup', max_grade=10, date=mirror.date,
            )])


def test_ac11_category_cannot_move_into_or_out_of_homework_in_the_model(db):
    homework = HomeworkFactory()
    mirror = SubjectAssignment.objects.get(category__code='homework', detail_id=homework.pk)

    mirror.category = AssignmentCategoryFactory(code='exam')
    mirror.detail_id = None
    with pytest.raises(ValidationError) as exc:
        mirror.save()
    assert 'category' in exc.value.message_dict

    plain = SubjectAssignmentFactory(offering=homework.offering, category='exam')
    plain.category = homework_category()
    plain.detail_id = homework.pk
    with pytest.raises(ValidationError):
        plain.save()


def test_ac11_category_cannot_move_into_or_out_of_homework_in_the_api(
    teacher, teaching_assignment, authenticated_client,
):
    client = authenticated_client(teacher.user)
    plain = SubjectAssignmentFactory(offering=teaching_assignment.offering, category='exam')
    homework = HomeworkFactory(teaching_assignment=teaching_assignment)
    mirror = SubjectAssignment.objects.get(category__code='homework', detail_id=homework.pk)

    assert client.patch(detail_url(plain), {'category': 'homework'}, format='json').status_code == 400
    assert client.patch(detail_url(mirror), {'category': 'exam'}, format='json').status_code == 400

    # Between two plain categories it is still allowed.
    response = client.patch(detail_url(plain), {'category': 'final'}, format='json')
    assert response.status_code == 200
    assert response.data['category'] == 'final'
