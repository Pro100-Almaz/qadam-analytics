"""
Spec 0017 — a homework's author is `created_by` (a Teacher), and its quarter
is stored on the Homework, set by the client and mirrored with its
SubjectAssignment's. No assignment's quarter is derived from its date.

Each test is named after the AC it pins down. AC-17 (the backfill) lives in
test_homework_created_by_migration.py.
"""

import datetime

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.home.models import SubjectAssignment
from apps.lesson.models import Homework, HomeworkGrade
from core.factories import (
    ClassGroupFactory, EnrollmentFactory, HomeworkFactory,
    SubjectAssignmentFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory,
)
from core.soft_delete import purge_batch

pytestmark = pytest.mark.django_db

D = datetime.date

HOMEWORK_CREATE_URL = reverse('lesson-api:homework-create')
ASSIGNMENTS_URL = reverse('home-api:subject-assignment-list-create')


def homework_url(homework):
    return reverse('lesson-api:homework-detail', args=[homework.pk])


def assignment_url(assignment):
    return reverse('home-api:subject-assignment-detail', args=[assignment.pk])


def grades_url(homework):
    return reverse('lesson-api:homework-grade-list-create', args=[homework.pk])


def teacher_homeworks_url(teacher):
    return reverse('lesson-api:teacher-homework-list', args=[teacher.pk])


def mirror(homework):
    return SubjectAssignment.objects.get(
        category__code='homework', detail_id=homework.pk,
    )


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
    """An offering whose teacher holds quarters 2 and 3, and a pupil in it."""
    class_group = ClassGroupFactory(academic_year=year)
    offering = SubjectOfferingFactory(class_group=class_group)
    teacher = TeacherFactory()
    assignments = {
        quarter: TeachingAssignmentFactory(
            offering=offering, teacher=teacher, quarter=quarter,
        )
        for quarter in (2, 3)
    }
    pupil = EnrollmentFactory(class_group=class_group).student
    return {
        'offering': offering, 'teacher': teacher,
        'assignments': assignments, 'pupil': pupil,
    }


def only_in(offering, quarter):
    """A second teacher of the offering, assigned for one quarter only."""
    return TeachingAssignmentFactory(offering=offering, quarter=quarter).teacher


def create_homework(client, offerings, **body):
    payload = {
        'offerings': [offering.pk for offering in offerings],
        'description': 'Exercises', 'max_grade': 10,
        'due_date': '2026-11-20', 'is_active': True, **body,
    }
    return client.post(HOMEWORK_CREATE_URL, payload, format='json')


def put_homework(client, homework, **body):
    payload = {
        'description': homework.description, 'max_grade': homework.max_grade,
        'due_date': homework.due_date.isoformat(),
        'is_active': homework.is_active, **body,
    }
    return client.put(homework_url(homework), payload, format='json')


def homework_in(world, quarter, **kwargs):
    return HomeworkFactory(
        teaching_assignment=world['assignments'][quarter], **kwargs,
    )


# ── Author ──

def test_ac1_create_records_the_author(world, authenticated_client):
    response = create_homework(
        authenticated_client(world['teacher'].user), [world['offering']], quarter=2,
    )

    assert response.status_code == 201, response.data
    homework = Homework.objects.get(pk=response.data[0]['id'])
    assert homework.created_by_id == world['teacher'].pk


def test_ac2_author_survives_teaching_assignment_purge(
    world, admin_user, authenticated_client, django_capture_on_commit_callbacks,
):
    homework = homework_in(world, 2)
    assignment = world['assignments'][2]
    assignment.delete()
    batch = type(assignment)._base_manager.get(pk=assignment.pk).deletion_batch
    with django_capture_on_commit_callbacks(execute=True):
        purge_batch(batch)

    homework.refresh_from_db()
    assert homework.created_by_id == world['teacher'].pk
    response = authenticated_client(admin_user).get(homework_url(homework))
    assert response.status_code == 200
    assert response.data['teacher'] == {
        'id': world['teacher'].user_id,
        'full_name': world['teacher'].user.get_full_name(),
    }


def test_ac3_homework_survives_its_authors_purge(
    world, admin_user, authenticated_client, django_capture_on_commit_callbacks,
):
    homework = homework_in(world, 2)
    teacher = world['teacher']
    teacher.delete()
    batch = type(teacher)._base_manager.get(pk=teacher.pk).deletion_batch
    with django_capture_on_commit_callbacks(execute=True):
        purge_batch(batch)

    homework.refresh_from_db()
    assert not homework.is_deleted
    assert homework.created_by_id is None
    response = authenticated_client(admin_user).get(homework_url(homework))
    assert response.status_code == 200
    assert response.data['teacher'] is None


def test_ac4_teacher_filters_follow_the_author(world, admin_user, authenticated_client):
    mine = homework_in(world, 2)
    colleague = only_in(world['offering'], 2)
    theirs = HomeworkFactory(
        created_by=colleague, offering=world['offering'], quarter=2,
    )
    client = authenticated_client(admin_user)

    listed = client.get(teacher_homeworks_url(world['teacher']))
    assert listed.status_code == 200
    assert [row['id'] for row in listed.data['results']] == [mine.pk]

    filtered = client.get(
        teacher_homeworks_url(colleague), {'teacher': colleague.pk},
    )
    assert [row['id'] for row in filtered.data['results']] == [theirs.pk]
    filtered = client.get(
        teacher_homeworks_url(colleague), {'teacher': world['teacher'].pk},
    )
    assert filtered.data['results'] == []


def test_ac5_teaching_assignment_is_gone(world, authenticated_client):
    homework = homework_in(world, 2)
    field_names = {field.name for field in Homework._meta.get_fields()}
    assert 'teaching_assignment' not in field_names

    response = authenticated_client(world['teacher'].user).get(homework_url(homework))
    assert response.status_code == 200
    assert 'teaching_assignment' not in response.data
    assert response.data['quarter'] == 2


# ── Quarter on create ──

@pytest.mark.parametrize('due_date', [
    '2026-09-15',  # inside quarter 1's bounds
    '2026-11-05',  # between quarters
    None,          # the year has no bounds at all
])
def test_ac6_create_stores_the_sent_quarter_whatever_the_date(
    world, authenticated_client, due_date,
):
    if due_date is None:
        year = world['offering'].academic_year
        for quarter in (1, 2, 3, 4):
            setattr(year, f'q{quarter}_start', None)
            setattr(year, f'q{quarter}_end', None)
        year.save()
        due_date = '2027-02-01'

    response = create_homework(
        authenticated_client(world['teacher'].user), [world['offering']],
        quarter=3, due_date=due_date,
    )

    assert response.status_code == 201, response.data
    homework = Homework.objects.get(pk=response.data[0]['id'])
    assert homework.quarter == 3
    assert mirror(homework).quarter == 3
    assert response.data[0]['quarter'] == 3


def test_ac7_create_without_quarter_is_400(world, authenticated_client):
    response = create_homework(
        authenticated_client(world['teacher'].user), [world['offering']],
    )

    assert response.status_code == 400
    assert 'quarter' in response.data
    assert not Homework.objects.exists()


def test_ac8_create_in_an_unassigned_quarter_is_403(world, authenticated_client):
    other = SubjectOfferingFactory(class_group=world['offering'].class_group)
    TeachingAssignmentFactory(offering=other, teacher=world['teacher'], quarter=1)
    client = authenticated_client(world['teacher'].user)

    single = create_homework(client, [other], quarter=2)
    batch = create_homework(client, [world['offering'], other], quarter=2)

    assert single.status_code == 403
    assert batch.status_code == 403
    assert batch.data['offerings'] == [other.pk]
    assert not Homework.objects.exists()


@pytest.mark.parametrize('category', ['lesson', 'homework'])
def test_ac9_subject_assignment_create_without_quarter_is_400(
    world, authenticated_client, category,
):
    response = authenticated_client(world['teacher'].user).post(ASSIGNMENTS_URL, {
        'offering': world['offering'].pk, 'title': 'Quiz', 'max_grade': 10,
        'date': '2026-11-20', 'category': category,
    }, format='json')

    assert response.status_code == 400
    assert 'quarter' in response.data
    assert not SubjectAssignment.objects.exists()
    assert not Homework.objects.exists()


# ── Quarter on update ──

def test_ac10_due_date_edit_keeps_the_quarter(world, authenticated_client):
    homework = homework_in(world, 2, due_date=D(2026, 11, 20))

    response = put_homework(
        authenticated_client(world['teacher'].user), homework, due_date='2027-02-01',
    )

    assert response.status_code == 200, response.data
    homework.refresh_from_db()
    assert homework.due_date == D(2027, 2, 1)
    assert homework.quarter == 2
    assert mirror(homework).quarter == 2


def test_ac11_quarter_edit_moves_homework_and_mirror(world, authenticated_client):
    homework = homework_in(world, 2)

    response = put_homework(
        authenticated_client(world['teacher'].user), homework, quarter=3,
    )

    assert response.status_code == 200, response.data
    assert response.data['quarter'] == 3
    homework.refresh_from_db()
    assert homework.quarter == 3
    assert mirror(homework).quarter == 3


def test_ac12_quarter_edit_into_an_unassigned_quarter_is_403(world, authenticated_client):
    homework = homework_in(world, 2)
    teacher = only_in(world['offering'], 2)

    response = put_homework(authenticated_client(teacher.user), homework, quarter=3)

    assert response.status_code == 403
    homework.refresh_from_db()
    assert homework.quarter == 2
    assert mirror(homework).quarter == 2


def test_ac13_mirror_quarter_edit_reaches_the_homework(world, authenticated_client):
    homework = homework_in(world, 2)

    response = authenticated_client(world['teacher'].user).patch(
        assignment_url(mirror(homework)), {'quarter': 3}, format='json',
    )

    assert response.status_code == 200, response.data
    homework.refresh_from_db()
    assert homework.quarter == 3


def test_ac14_subject_assignment_date_edit_keeps_the_quarter(world, authenticated_client):
    TeachingAssignmentFactory(
        offering=world['offering'], teacher=world['teacher'], quarter=1,
    )
    assignment = SubjectAssignmentFactory(
        offering=world['offering'], date=D(2026, 9, 15), quarter=1,
    )

    response = authenticated_client(world['teacher'].user).patch(
        assignment_url(assignment), {'date': '2027-04-10'}, format='json',
    )

    assert response.status_code == 200, response.data
    assert response.data['quarter'] == 1
    assignment.refresh_from_db()
    assert assignment.quarter == 1


def test_ac15_model_save_leaves_a_missing_quarter_missing(world):
    assignment = SubjectAssignmentFactory(
        offering=world['offering'], date=D(2026, 11, 20), quarter=None,
    )

    assignment.refresh_from_db()
    assert assignment.quarter is None


# ── Access follows the stored quarter ──

def test_ac16_access_follows_the_stored_quarter_not_the_date(
    world, authenticated_client,
):
    homework = homework_in(world, 2, due_date=D(2026, 11, 5))  # between quarters
    stranger_user = only_in(world['offering'], 1).user
    # One shared client: each authenticated_client() call re-authenticates it.
    owner = authenticated_client(world['teacher'].user)

    detail = owner.get(homework_url(homework))
    assert detail.status_code == 200
    assert detail.data['can_edit'] is True

    assert put_homework(owner, homework, description='Edited').status_code == 200
    graded = owner.post(
        grades_url(homework), {'student': world['pupil'].pk, 'grade': 8}, format='json',
    )
    assert graded.status_code == 201, graded.data
    assert HomeworkGrade.objects.filter(homework=homework).exists()

    stranger = authenticated_client(stranger_user)
    assert put_homework(stranger, homework, description='Nope').status_code == 403
    assert stranger.delete(homework_url(homework)).status_code == 403

    owner = authenticated_client(world['teacher'].user)
    assert owner.delete(homework_url(homework)).status_code == 204


# ── Drift ──

def test_ac18_sync_command_reports_and_fixes_quarter_drift(world, capsys):
    homework = homework_in(world, 2)
    SubjectAssignment.objects.filter(pk=mirror(homework).pk).update(quarter=4)

    with pytest.raises(CommandError):
        call_command('sync_homework_assignments', '--check')
    assert 'quarter' in capsys.readouterr().out

    call_command('sync_homework_assignments', '--fix')
    call_command('sync_homework_assignments', '--check')
    assert mirror(homework).quarter == 2
    homework.refresh_from_db()
    assert homework.quarter == 2
