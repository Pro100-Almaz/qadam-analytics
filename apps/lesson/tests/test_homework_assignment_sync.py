"""
Spec 0005 — Homework and its SubjectAssignment mirror stay in step.

AC-13 … AC-23. Every Homework has one SubjectAssignment of category `homework`
(`detail_id` = the homework's pk), every HomeworkGrade a SubjectGrade on it,
and a write to either side reaches the other — through the API, the model and
the admin alike.
"""

import datetime

import pytest
from django.contrib import admin
from django.core.management import CommandError, call_command
from django.test import RequestFactory
from django.urls import reverse

from apps.home.models import HomeroomTeacherAssignment, SubjectAssignment, SubjectGrade
from apps.lesson.models import Homework, HomeworkGrade
from apps.student_report.services.grade_sheet import collect_grade_sheet
from core.factories import (
    EnrollmentFactory, HomeworkFactory, HomeworkGradeFactory, ParentFactory,
    StudentFactory, SubjectOfferingFactory, TeacherFactory,
    TeachingAssignmentFactory, UserFactory,
)

HOMEWORK_CREATE_URL = reverse('lesson-api:homework-create')
ASSIGNMENTS_URL = reverse('home-api:subject-assignment-list-create')
SUBJECT_GRADES_URL = reverse('home-api:subject-grade-list')
HOMEROOM_ASSIGNMENTS_URL = reverse('home-api:homeroom-subject-assignment-list')


def homework_url(homework):
    return reverse('lesson-api:homework-detail', args=[homework.pk])


def assignment_url(assignment):
    return reverse('home-api:subject-assignment-detail', args=[assignment.pk])


def trajectory_url(student, offering):
    return reverse(
        'lesson-api:analytics-assignment-trajectory', args=[student.pk, offering.pk],
    )


def mirror(homework):
    return SubjectAssignment.objects.get(category__code='homework', detail_id=homework.pk)


def assert_mirrors(homework):
    assignment = mirror(homework)
    assert assignment.offering_id == homework.offering_id
    assert assignment.title == homework.description
    assert assignment.max_grade == homework.max_grade
    assert assignment.date == homework.due_date
    assert assignment.is_active == homework.is_active
    return assignment


@pytest.fixture
def pupil(class_group):
    student = StudentFactory()
    EnrollmentFactory(student=student, class_group=class_group)
    return student


@pytest.fixture
def homework(teaching_assignment):
    return HomeworkFactory(
        teaching_assignment=teaching_assignment,
        description='Read chapter 3', max_grade=10,
        due_date=datetime.date(2026, 10, 5),
    )


# ── Homework -> assignment ──

def test_ac13_bulk_homework_create_mirrors_every_offering(
    teacher, teaching_assignment, authenticated_client,
):
    second = TeachingAssignmentFactory(
        teacher=teacher,
        offering=SubjectOfferingFactory(class_group=teaching_assignment.offering.class_group),
    )

    response = authenticated_client(teacher.user).post(HOMEWORK_CREATE_URL, {
        'offerings': [teaching_assignment.offering_id, second.offering_id],
        'description': 'Exercises 1-10', 'max_grade': 20,
        'due_date': '2026-10-07', 'is_active': True,
    }, format='json')

    assert response.status_code == 201, response.data
    created = Homework.objects.filter(pk__in=[row['id'] for row in response.data])
    assert created.count() == 2
    for homework in created:
        assert_mirrors(homework)


def test_ac14_homework_put_updates_the_mirror(teacher, homework, authenticated_client):
    response = authenticated_client(teacher.user).put(homework_url(homework), {
        'description': 'Read chapter 4', 'max_grade': 15,
        'due_date': '2026-10-09', 'is_active': False,
    }, format='json')

    assert response.status_code == 200, response.data
    homework.refresh_from_db()
    assignment = assert_mirrors(homework)
    assert assignment.title == 'Read chapter 4'
    assert assignment.is_active is False


def test_ac15_homework_delete_removes_mirror_and_its_grades(
    teacher, homework, pupil, authenticated_client,
):
    HomeworkGradeFactory(homework=homework, student=pupil, grade=8)
    assignment = mirror(homework)
    assert SubjectGrade.objects.filter(assignment=assignment).count() == 1

    response = authenticated_client(teacher.user).delete(homework_url(homework))

    assert response.status_code == 204
    assert not SubjectAssignment.objects.filter(pk=assignment.pk).exists()
    assert not SubjectGrade.objects.filter(assignment_id=assignment.pk).exists()


# ── Assignment -> homework ──

def test_ac16_homework_category_assignment_creates_the_homework(
    teacher, teaching_assignment, authenticated_client,
):
    response = authenticated_client(teacher.user).post(ASSIGNMENTS_URL, {
        'offering': teaching_assignment.offering_id, 'title': 'Essay',
        'max_grade': 25, 'date': '2026-10-10', 'category': 'homework',
        'is_active': False,
    }, format='json')

    assert response.status_code == 201, response.data
    homework = Homework.objects.get(pk=response.data['detail_id'])
    assert homework.teaching_assignment_id == teaching_assignment.pk
    assert homework.description == 'Essay'
    assert homework.is_active is False
    assert response.data['id'] == assert_mirrors(homework).pk


def test_ac16_homework_category_max_grade_is_capped_at_100(
    teacher, teaching_assignment, authenticated_client,
):
    response = authenticated_client(teacher.user).post(ASSIGNMENTS_URL, {
        'offering': teaching_assignment.offering_id, 'title': 'Essay',
        'max_grade': 101, 'date': '2026-10-10', 'category': 'homework',
    }, format='json')

    assert response.status_code == 400
    assert 'max_grade' in response.data
    assert not Homework.objects.exists()


def test_ac17_assignment_patch_updates_the_homework(teacher, homework, authenticated_client):
    response = authenticated_client(teacher.user).patch(assignment_url(mirror(homework)), {
        'title': 'Read chapter 5', 'max_grade': 12, 'date': '2026-10-12', 'is_active': False,
    }, format='json')

    assert response.status_code == 200, response.data
    homework.refresh_from_db()
    assert homework.description == 'Read chapter 5'
    assert homework.max_grade == 12
    assert homework.due_date == datetime.date(2026, 10, 12)
    assert homework.is_active is False


# AC-18 (deleting the assignment deletes the Homework) is superseded by spec
# 0007: see test_homework_assignment_delete.py.


# ── Grades ──

def test_ac19_homework_grade_writes_reach_the_subject_grade(homework, pupil):
    grade = HomeworkGradeFactory(homework=homework, student=pupil, grade=6, comments='ok')
    subject_grade = SubjectGrade.objects.get(assignment=mirror(homework), student=pupil)
    assert (subject_grade.grade, subject_grade.comments) == (6, 'ok')

    grade.grade = 9
    grade.comments = None
    grade.save()
    subject_grade.refresh_from_db()
    assert (subject_grade.grade, subject_grade.comments) == (9, None)

    grade.delete()
    assert not SubjectGrade.objects.filter(assignment=mirror(homework), student=pupil).exists()


def test_ac19_subject_grade_writes_reach_the_homework_grade(
    teacher, homework, pupil, authenticated_client,
):
    client = authenticated_client(teacher.user)
    response = client.post(
        reverse('home-api:subject-assignment-grade-list-create', args=[mirror(homework).pk]),
        {'student': pupil.pk, 'grade': 5, 'comments': 'late'}, format='json',
    )
    assert response.status_code == 201, response.data
    homework_grade = HomeworkGrade.objects.get(homework=homework, student=pupil)
    assert (homework_grade.grade, homework_grade.comments) == (5, 'late')

    subject_grade = SubjectGrade.objects.get(pk=response.data['id'])
    subject_grade.grade = 10
    subject_grade.save()
    homework_grade.refresh_from_db()
    assert homework_grade.grade == 10

    subject_grade.delete()
    assert not HomeworkGrade.objects.filter(homework=homework, student=pupil).exists()


# ── Admin, cascades, command ──

def test_ac20_admin_save_and_bulk_delete_sync(homework, pupil):
    from apps.lesson.admin import HomeworkAdmin, HomeworkGradeAdmin

    request = RequestFactory().post('/admin/')
    request.user = UserFactory(is_staff=True, is_superuser=True)
    request._messages = None

    homework.description = 'Changed in admin'
    HomeworkAdmin(Homework, admin.site).save_model(request, homework, form=None, change=True)
    assert mirror(homework).title == 'Changed in admin'

    HomeworkGradeFactory(homework=homework, student=pupil, grade=4)
    HomeworkGradeAdmin(HomeworkGrade, admin.site).delete_queryset(
        request, HomeworkGrade.objects.filter(homework=homework),
    )
    assert not SubjectGrade.objects.filter(assignment=mirror(homework)).exists()

    assignment_id = mirror(homework).pk
    HomeworkAdmin(Homework, admin.site).delete_queryset(
        request, Homework.objects.filter(pk=homework.pk),
    )
    assert not SubjectAssignment.objects.filter(pk=assignment_id).exists()


def test_ac21_teaching_assignment_delete_leaves_no_orphan(teaching_assignment, homework):
    assignment_id = mirror(homework).pk

    teaching_assignment.delete()

    assert not Homework.objects.filter(pk=homework.pk).exists()
    assert not SubjectAssignment.objects.filter(pk=assignment_id).exists()


def test_ac22_sync_command_detects_and_fixes_drift(homework, pupil, capsys):
    HomeworkGradeFactory(homework=homework, student=pupil, grade=3)
    call_command('sync_homework_assignments', '--check')

    # Writes the hooks cannot see: QuerySet.update() and QuerySet.delete().
    SubjectAssignment.objects.filter(pk=mirror(homework).pk).update(title='drifted')
    SubjectGrade.objects.filter(assignment=mirror(homework)).update(grade=1)
    gone = HomeworkFactory(teaching_assignment=homework.teaching_assignment)
    Homework.objects.filter(pk=gone.pk).delete()

    with pytest.raises(CommandError):
        call_command('sync_homework_assignments', '--check')
    out = capsys.readouterr().out
    assert 'assignment_drift' in out
    assert 'grade_drift' in out
    assert 'orphan_assignment' in out

    call_command('sync_homework_assignments', '--fix')
    call_command('sync_homework_assignments', '--check')
    assert_mirrors(homework)
    assert SubjectGrade.objects.get(assignment=mirror(homework), student=pupil).grade == 3
    assert not SubjectAssignment.objects.filter(category__code='homework', detail_id=gone.pk).exists()


# ── Drafts ──

def test_ac23_draft_homework_is_hidden_from_students_and_analytics(
    teacher, teaching_assignment, pupil, authenticated_client,
):
    draft = HomeworkFactory(teaching_assignment=teaching_assignment, is_active=False)
    published = HomeworkFactory(teaching_assignment=teaching_assignment, is_active=True)
    HomeworkGradeFactory(homework=draft, student=pupil, grade=5)
    HomeworkGradeFactory(homework=published, student=pupil, grade=5)
    assert mirror(draft).is_active is False

    student_client = authenticated_client(pupil.user)
    seen = {row['id'] for row in student_client.get(ASSIGNMENTS_URL).data['results']}
    assert seen == {mirror(published).pk}
    graded = {row['assignment']['id'] for row in student_client.get(SUBJECT_GRADES_URL).data['results']}
    assert graded == {mirror(published).pk}

    trajectory = student_client.get(trajectory_url(pupil, teaching_assignment.offering))
    assert trajectory.status_code == 200, trajectory.data
    assert [p['id'] for p in trajectory.data['points']] == [mirror(published).pk]

    teacher_client = authenticated_client(teacher.user)
    seen = {row['id'] for row in teacher_client.get(ASSIGNMENTS_URL).data['results']}
    assert seen == {mirror(draft).pk, mirror(published).pk}


def test_ac23_draft_homework_is_hidden_from_parents_homeroom_and_grade_sheets(
    teacher, teaching_assignment, pupil, academic_year, authenticated_client,
):
    academic_year.q1_start = datetime.date(2026, 9, 1)
    academic_year.q1_end = datetime.date(2026, 10, 31)
    academic_year.save()
    due = datetime.date(2026, 10, 5)
    draft = HomeworkFactory(teaching_assignment=teaching_assignment, is_active=False, due_date=due)
    published = HomeworkFactory(teaching_assignment=teaching_assignment, is_active=True, due_date=due)
    class_group = teaching_assignment.offering.class_group

    parent = ParentFactory()
    parent.students.add(pupil)
    seen = {row['id'] for row in authenticated_client(parent.user).get(ASSIGNMENTS_URL).data['results']}
    assert seen == {mirror(published).pk}

    homeroom_teacher = TeacherFactory()
    HomeroomTeacherAssignment.objects.create(teacher=homeroom_teacher, class_group=class_group)
    rows = authenticated_client(homeroom_teacher.user).get(HOMEROOM_ASSIGNMENTS_URL).data['results']
    assert {row['id'] for row in rows} == {mirror(published).pk}

    sheet = collect_grade_sheet(
        class_group=class_group, academic_year=academic_year, quarter=1, students=[pupil],
    )
    columns = [c.assignment_id for block in sheet.subjects for c in block.columns]
    assert columns == [mirror(published).pk]
    assert mirror(draft).pk not in columns
