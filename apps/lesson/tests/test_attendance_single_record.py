"""
Spec 0004 — one attendance record per lesson slot.

A slot is `(session, student, date)`. The client bug behind the spec: a teacher
re-saving a register POSTed every student again, the rows that already existed
were refused with 400 "already recorded", and the corrected mark was lost while
the parent kept reading the earlier one. POST now updates the existing row, and
the database refuses a second row for the slot outright.
"""

import datetime
import threading
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models.query import QuerySet
from django.urls import reverse

from apps.home.models import Enrollment
from apps.lesson.models import ScheduleAttendance
from apps.lesson.services import record_attendance
from core.factories import (
    AdminUserFactory,
    ClassGroupFactory,
    ParentFactory,
    ScheduleAttendanceFactory,
    ScheduleSessionFactory,
    StudentFactory,
    SubjectOfferingFactory,
    SubjectScheduleFactory,
    TeacherFactory,
    TeachingAssignmentFactory,
)
from core.tenancy import get_active_school, school_scope

DAY = datetime.date(2026, 9, 24)


@pytest.fixture
def slot(academic_year):
    """One enrolled student, one session of an offering taught by `teacher`."""
    class_group = ClassGroupFactory(academic_year=academic_year)
    offering = SubjectOfferingFactory(class_group=class_group)
    teacher = TeacherFactory()
    TeachingAssignmentFactory(offering=offering, teacher=teacher)
    session = ScheduleSessionFactory(
        schedule=SubjectScheduleFactory(offering=offering),
    )
    student = StudentFactory()
    Enrollment.enroll_student(student, class_group)
    return SimpleNamespace(
        class_group=class_group, offering=offering, teacher=teacher,
        session=session, student=student,
    )


# ── AC-1: the database refuses a second row for a slot ──

@pytest.mark.django_db
def test_ac1_db_rejects_second_row_for_same_slot(slot):
    ScheduleAttendanceFactory(
        session=slot.session, student=slot.student, date=DAY, status='absent',
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ScheduleAttendance.objects.create(
            session=slot.session, student=slot.student, date=DAY, status='present',
        )


# ── Write path: POST upserts the slot ──

def attendance_url(session):
    return reverse('lesson-api:schedule-attendance-list-create', args=[session.id])


def detail_url(attendance):
    return reverse('lesson-api:schedule-attendance-detail', args=[attendance.id])


def student_list_url(student):
    return reverse('lesson-api:student-attendance-list', args=[student.id])


def mark(student, status, date=DAY):
    return {'student': student.id, 'date': date.isoformat(), 'status': status}


@pytest.mark.django_db
def test_ac2_post_to_recorded_slot_updates_it_and_returns_200(slot, authenticated_client):
    existing = ScheduleAttendanceFactory(
        session=slot.session, student=slot.student, date=DAY, status='absent',
    )
    client = authenticated_client(slot.teacher.user)

    response = client.post(attendance_url(slot.session), mark(slot.student, 'present'))

    assert response.status_code == 200
    assert response.data['id'] == existing.id
    assert response.data['status'] == 'present'
    assert ScheduleAttendance.objects.filter(
        session=slot.session, student=slot.student, date=DAY,
    ).count() == 1


@pytest.mark.django_db
def test_ac3_post_to_empty_slot_creates_and_returns_201(slot, authenticated_client):
    client = authenticated_client(slot.teacher.user)

    response = client.post(attendance_url(slot.session), mark(slot.student, 'present'))

    assert response.status_code == 201
    assert ScheduleAttendance.objects.filter(
        session=slot.session, student=slot.student, date=DAY,
    ).count() == 1


@pytest.mark.django_db
def test_ac7_parent_sees_one_present_row_after_correction(slot, authenticated_client):
    ScheduleAttendanceFactory(
        session=slot.session, student=slot.student, date=DAY, status='absent',
    )
    parent = ParentFactory()
    parent.students.add(slot.student)

    teacher_client = authenticated_client(slot.teacher.user)
    teacher_client.post(attendance_url(slot.session), mark(slot.student, 'present'))

    parent_client = authenticated_client(parent.user)
    response = parent_client.get(student_list_url(slot.student))

    assert response.status_code == 200
    rows = [row for row in response.data['results'] if row['date'] == DAY.isoformat()]
    assert [row['status'] for row in rows] == ['present']


@pytest.mark.django_db
def test_ac12_save_records_marked_by_and_updated_at(slot, authenticated_client):
    client = authenticated_client(slot.teacher.user)
    created = client.post(attendance_url(slot.session), mark(slot.student, 'absent'))
    assert created.status_code == 201
    assert created.data['marked_by'] == slot.teacher.user.id
    assert created.data['updated_at'] is not None

    admin = AdminUserFactory()
    client = authenticated_client(admin)
    updated = client.post(attendance_url(slot.session), mark(slot.student, 'present'))
    assert updated.status_code == 200
    assert updated.data['marked_by'] == admin.id
    assert updated.data['updated_at'] >= created.data['updated_at']

    client = authenticated_client(slot.teacher.user)
    row = ScheduleAttendance.objects.get(pk=created.data['id'])
    patched = client.patch(detail_url(row), {'status': 'absent'})
    assert patched.status_code == 200
    assert patched.data['marked_by'] == slot.teacher.user.id

    # A row nobody marked through the API carries no marker.
    untouched = ScheduleAttendanceFactory(
        session=slot.session, student=StudentFactory(), date=DAY,
    )
    assert untouched.marked_by is None


@pytest.mark.django_db
def test_ac13_register_resave_applies_the_changed_mark(slot, authenticated_client):
    """The production burst: the whole register POSTed again, one mark changed."""
    flipped = slot.student
    unchanged = StudentFactory()
    newcomer = StudentFactory()
    for student in (unchanged, newcomer):
        Enrollment.enroll_student(student, slot.class_group)
    ScheduleAttendanceFactory(session=slot.session, student=flipped, date=DAY, status='absent')
    ScheduleAttendanceFactory(session=slot.session, student=unchanged, date=DAY, status='present')

    client = authenticated_client(slot.teacher.user)
    register = [(flipped, 'present'), (unchanged, 'present'), (newcomer, 'absent')]
    codes = [
        client.post(attendance_url(slot.session), mark(student, status)).status_code
        for student, status in register
    ]

    assert codes == [200, 200, 201]
    assert ScheduleAttendance.objects.get(
        session=slot.session, student=flipped, date=DAY,
    ).status == 'present'


# ── AC-4: racing saves leave one row, carrying the last committed status ──

@pytest.mark.django_db(transaction=True)
def test_ac4_racing_posts_leave_one_row_with_last_status(slot):
    """Two requests for one empty slot, released at the same instant."""
    school = get_active_school()
    barrier = threading.Barrier(2)
    finished = []
    errors = []
    lock = threading.Lock()

    def save(status):
        try:
            with school_scope(school):
                barrier.wait()
                record_attendance(
                    slot.session, slot.student, DAY, status, slot.teacher.user,
                )
            # Autocommit: returning means committed, so finish order is
            # commit order.
            with lock:
                finished.append(status)
        except Exception as exc:  # noqa: BLE001 — surfaced by the assert below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=save, args=(s,)) for s in ('absent', 'present')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    rows = ScheduleAttendance.objects.filter(
        session=slot.session, student=slot.student, date=DAY,
    )
    assert rows.count() == 1
    assert rows.get().status == finished[-1]


@pytest.mark.django_db
def test_ac4_losing_insert_updates_the_winner_row(slot, monkeypatch):
    """
    The race path, forced deterministically: the lookup misses although the
    row exists, as it would for a request that read just before a concurrent
    insert committed. The insert then trips the constraint, and the loser's
    status must still be applied rather than raising or being dropped.
    """
    winner = ScheduleAttendanceFactory(
        session=slot.session, student=slot.student, date=DAY, status='absent',
    )
    real_get = QuerySet.get
    missed = []

    def get_that_misses_once(self, *args, **kwargs):
        if self.model is ScheduleAttendance and not missed:
            missed.append(True)
            raise ScheduleAttendance.DoesNotExist
        return real_get(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, 'get', get_that_misses_once)

    attendance, created = record_attendance(
        slot.session, slot.student, DAY, 'present', slot.teacher.user,
    )

    assert missed == [True]
    assert created is False
    assert attendance.pk == winner.pk
    assert ScheduleAttendance.objects.get(pk=winner.pk).status == 'present'
    assert ScheduleAttendance.objects.filter(
        session=slot.session, student=slot.student, date=DAY,
    ).count() == 1


# ── AC-5: PATCH never merges two rows ──

@pytest.fixture
def two_rows(slot):
    """Two students with a row each in the same slot."""
    other = StudentFactory()
    Enrollment.enroll_student(other, slot.class_group)
    first = ScheduleAttendanceFactory(
        session=slot.session, student=slot.student, date=DAY, status='absent',
    )
    second = ScheduleAttendanceFactory(
        session=slot.session, student=other, date=DAY, status='present',
    )
    return first, second


def unchanged(*rows):
    return all(
        ScheduleAttendance.objects.filter(
            pk=row.pk, student=row.student, date=row.date, status=row.status,
        ).exists()
        for row in rows
    )


@pytest.mark.django_db
def test_ac5_patch_onto_occupied_slot_is_400_and_changes_nothing(
    slot, two_rows, authenticated_client
):
    first, second = two_rows
    client = authenticated_client(slot.teacher.user)

    response = client.patch(detail_url(second), {'student': first.student.id})

    assert response.status_code == 400
    assert unchanged(first, second)


@pytest.mark.django_db
def test_ac5_patch_racing_an_insert_is_still_400(
    slot, two_rows, authenticated_client, monkeypatch
):
    """
    The serializer check passed, but the slot filled before the write — the
    database constraint is what refuses it, and that must surface as a 400,
    not a 500.
    """
    from apps.lesson.api.serializers import ScheduleAttendanceWriteSerializer

    first, second = two_rows
    monkeypatch.setattr(
        ScheduleAttendanceWriteSerializer, 'validate', lambda self, attrs: attrs,
    )
    client = authenticated_client(slot.teacher.user)

    response = client.patch(detail_url(second), {'student': first.student.id})

    assert response.status_code == 400
    assert 'already recorded' in str(response.data)
    assert unchanged(first, second)


# ── AC-8: the student list has a total order ──

@pytest.mark.django_db
def test_ac8_student_list_order_is_stable_on_ties(slot, authenticated_client):
    """
    Lessons at the same date and time (a subject split across подгруппы) tie
    on every ordering key but `id`. Updating rows moves them to the end of the
    heap, scrambling physical order against id order, so without the tiebreak
    Postgres hands them back in whatever order the scan found them.
    """
    sessions = [slot.session] + [
        ScheduleSessionFactory(
            schedule=SubjectScheduleFactory(
                offering=SubjectOfferingFactory(class_group=slot.class_group),
            ),
            weekday=slot.session.weekday,
            time_start=slot.session.time_start,
            time_end=slot.session.time_end,
        )
        for _ in range(5)
    ]
    rows = [
        ScheduleAttendanceFactory(session=session, student=slot.student, date=DAY)
        for session in sessions
    ]
    for row in (rows[0], rows[3], rows[1]):
        ScheduleAttendance.objects.filter(pk=row.pk).update(status='absent')

    client = authenticated_client(slot.teacher.user)
    first = [r['id'] for r in client.get(student_list_url(slot.student)).data['results']]
    second = [r['id'] for r in client.get(student_list_url(slot.student)).data['results']]

    assert first == second == [row.id for row in rows]
