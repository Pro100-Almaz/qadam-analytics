from datetime import date, time
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status

from apps.achievement.models import (
    MAX_ATTACHMENT_SIZE_BYTES,
    Attachment,
    ClubAttendance,
    ClubSession,
)
from apps.authentication.models import CustomUser
from core.factories import (
    ClubFactory,
    ClubManagerFactory,
    ClubSessionFactory,
    EnrollmentFactory,
    ParentFactory,
    StudentFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def _valid_png_bytes():
    buffer = BytesIO()
    Image.new('RGB', (2, 2), color='red').save(buffer, format='PNG')
    return buffer.getvalue()


def _club_payload(year, manager, **overrides):
    payload = {
        'club_name': 'Robotics Club',
        'academic_year_id': year.id,
        'start_date': '2026-09-01',
        'end_date': '2027-05-31',
        'plan': 'Build robots.',
        'criteria': 'Completed prototype.',
        'schedule': [{
            'weekday': 'wednesday',
            'start_time': '16:00',
            'end_time': '17:30',
            'location': 'STEM Lab',
        }],
    }
    payload.update(overrides)
    return payload


class TestClubPermissionsAndCrud:
    def test_admin_registration_creates_club_manager_profile(
        self, authenticated_client, admin_user
    ):
        response = authenticated_client(admin_user).post(
            reverse('auth-api:register'),
            {
                'first_name': 'Club',
                'last_name': 'Manager',
                'email': 'club.manager@test.kz',
                'password1': 'testpass123',
                'password2': 'testpass123',
                'role': CustomUser.GROUP_CLUB_MANAGER,
            },
            format='multipart',
        )
        assert response.status_code == status.HTTP_201_CREATED
        user = CustomUser.objects.get(email='club.manager@test.kz')
        assert user.is_club_manager()
        assert user.clubmanager.user_id == user.id

    def test_admin_creates_and_lists_club(
        self, authenticated_client, admin_user, academic_year
    ):
        manager = ClubManagerFactory(user=admin_user)
        client = authenticated_client(admin_user)
        response = client.post(
            reverse('achievement-api:club-list-create'),
            _club_payload(academic_year, manager),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['club_name'] == 'Robotics Club'
        assert response.data['status'] == 'pending'
        assert response.data['sessions_per_week'] == 1
        assert response.data['member_count'] == 0
        assert response.data['schedule'][0]['weekday'] == 'wednesday'

        listing = client.get(reverse('achievement-api:club-list-create'), {
            'search': 'robot',
            'academic_year': academic_year.id,
            'page_size': 20,
        })
        assert listing.status_code == status.HTTP_200_OK
        assert listing.data['count'] == 1

    def test_create_fails_when_current_user_has_no_club_manager_profile(
        self, authenticated_client, admin_user, academic_year
    ):
        manager = ClubManagerFactory()
        response = authenticated_client(admin_user).post(
            reverse('achievement-api:club-list-create'),
            _club_payload(academic_year, manager),
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['manager'][0] == (
            'No ClubManager profile exists for the authenticated user.'
        )

    def test_manager_only_sees_assigned_clubs(self, authenticated_client, academic_year):
        manager = ClubManagerFactory()
        other = ClubManagerFactory()
        mine = ClubFactory(manager=manager, academic_year=academic_year)
        ClubFactory(manager=other, academic_year=academic_year)

        client = authenticated_client(manager.user)
        listing = client.get(reverse('achievement-api:club-list-create'))
        assert listing.status_code == status.HTTP_200_OK
        assert [row['id'] for row in listing.data['results']] == [mine.id]

        denied = client.get(reverse(
            'achievement-api:club-detail', kwargs={'pk': other.clubs.first().id}
        ))
        assert denied.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize('group_name', [
        CustomUser.GROUP_TEACHER,
        CustomUser.GROUP_STUDENT,
        CustomUser.GROUP_PARENT,
    ])
    def test_unsupported_roles_receive_403(self, authenticated_client, group_name):
        user = UserFactory(group_name=group_name)
        response = authenticated_client(user).get(
            reverse('achievement-api:club-list-create')
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['detail'] == 'You do not have permission to perform this action.'

    def test_schedule_overlap_and_date_validation(
        self, authenticated_client, admin_user, academic_year
    ):
        manager = ClubManagerFactory(user=admin_user)
        client = authenticated_client(admin_user)
        overlap = _club_payload(academic_year, manager, schedule=[
            {
                'weekday': 'wednesday', 'start_time': '16:00',
                'end_time': '17:30', 'location': 'A',
            },
            {
                'weekday': 'wednesday', 'start_time': '17:00',
                'end_time': '18:00', 'location': 'B',
            },
        ])
        response = client.post(
            reverse('achievement-api:club-list-create'), overlap, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'overlap' in response.data['schedule'][0]

        invalid_dates = _club_payload(
            academic_year, manager,
            start_date='2027-01-01', end_date='2026-01-01',
        )
        response = client.post(
            reverse('achievement-api:club-list-create'), invalid_dates, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'end_date' in response.data

    def test_patch_updates_club_status_but_reserves_deleted_for_delete_endpoint(
        self, authenticated_client, admin_user, academic_year
    ):
        club = ClubFactory(academic_year=academic_year, status='pending')
        client = authenticated_client(admin_user)
        url = reverse('achievement-api:club-detail', kwargs={'pk': club.id})

        activated = client.patch(url, {'status': 'active'}, format='json')
        assert activated.status_code == status.HTTP_200_OK
        assert activated.data['status'] == 'active'

        finished = client.patch(url, {'status': 'finished'}, format='json')
        assert finished.status_code == status.HTTP_200_OK
        assert finished.data['status'] == 'finished'

        rejected = client.patch(url, {'status': 'deleted'}, format='json')
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST
        assert 'DELETE endpoint' in rejected.data['status'][0]
        club.refresh_from_db()
        assert club.status == 'finished'
        assert club.is_deleted is False

    def test_put_replaces_schedule_and_delete_soft_deletes_graph(
        self, authenticated_client, admin_user, academic_year
    ):
        manager = ClubManagerFactory()
        club = ClubFactory(
            manager=manager, academic_year=academic_year,
            start_date=date(2026, 9, 1), end_date=date(2027, 5, 31),
        )
        old = ClubSessionFactory(
            club=club, weekday='monday', start_time=time(15), end_time=time(16)
        )
        client = authenticated_client(admin_user)
        payload = _club_payload(academic_year, manager, schedule=[{
            'weekday': 'friday', 'start_time': '15:00',
            'end_time': '16:00', 'location': 'Library',
        }])
        response = client.put(
            reverse('achievement-api:club-detail', kwargs={'pk': club.id}),
            payload,
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        old.refresh_from_db()
        assert old.is_deleted is True
        assert response.data['schedule'][0]['weekday'] == 'friday'

        active_session = ClubSession.objects.get(club=club)
        student = StudentFactory(academic_year=academic_year)
        club.members.add(student)
        attendance = ClubAttendance.objects.create(
            session=active_session,
            student=student,
            date=date(2026, 9, 4),
            status='present',
        )
        deleted = client.delete(reverse(
            'achievement-api:club-detail', kwargs={'pk': club.id}
        ))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        club.refresh_from_db()
        active_session.refresh_from_db()
        attendance.refresh_from_db()
        assert club.is_deleted and active_session.is_deleted and attendance.is_deleted
        assert club.status == 'deleted'
        assert club.members.filter(pk=student.id).exists()


class TestStudentClubList:
    def test_student_gets_only_their_clubs_with_details(
        self, authenticated_client, academic_year
    ):
        student = StudentFactory(academic_year=academic_year)
        first = ClubFactory(
            academic_year=academic_year,
            name='Chess Club',
            status='active',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
        )
        second = ClubFactory(
            academic_year=academic_year,
            name='Robotics Club',
            status='active',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
        )
        ClubFactory(academic_year=academic_year, name='Not My Club')
        first.members.add(student)
        second.members.add(student)
        pending = ClubFactory(academic_year=academic_year, status='pending')
        finished = ClubFactory(academic_year=academic_year, status='finished')
        pending.members.add(student)
        finished.members.add(student)
        session = ClubSessionFactory(
            club=first,
            weekday='monday',
            start_time=time(15, 30),
            end_time=time(16, 30),
            location='Room 204',
        )
        for attendance_date, attendance_status in (
            (date(2026, 9, 7), 'present'),
            (date(2026, 9, 14), 'late'),
            (date(2026, 9, 21), 'absent'),
        ):
            ClubAttendance.objects.create(
                session=session,
                student=student,
                date=attendance_date,
                status=attendance_status,
            )

        response = authenticated_client(student.user).get(
            reverse('achievement-api:student-clubs', kwargs={'student_id': student.id})
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 2
        assert {row['id'] for row in response.data['results']} == {first.id, second.id}
        chess = next(row for row in response.data['results'] if row['id'] == first.id)
        assert chess['club_name'] == 'Chess Club'
        assert chess['student'] == {
            'id': student.id,
            'full_name': student.user.get_full_name() or student.user.username,
        }
        assert chess['academic_year'] == academic_year.year
        assert chess['created_at']
        assert 'schedule' not in chess
        assert 'attachments' not in chess
        assert 'member_count' not in chess
        assert 'attendance_dates_count' not in chess
        assert chess['total_session_count'] == 3
        assert chess['present_count'] == 1
        assert chess['late_count'] == 1
        assert chess['absent_count'] == 1

        detail = authenticated_client(student.user).get(reverse(
            'achievement-api:student-club-detail',
            kwargs={'student_id': student.id, 'club_id': first.id},
        ))
        assert detail.status_code == status.HTTP_200_OK
        assert detail.data['status'] == 'active'
        assert detail.data['total_session_count'] == 3
        assert detail.data['schedule'][0]['id'] == session.id
        assert 'plan' in detail.data
        assert 'criteria' in detail.data

        attendance_url = reverse(
            'achievement-api:student-club-attendance',
            kwargs={'student_id': student.id, 'club_id': first.id},
        )
        attendance_page = authenticated_client(student.user).get(attendance_url, {
            'date_from': '2026-09-01',
            'date_to': '2026-09-28',
            'page': 1,
            'page_size': 2,
        })
        assert attendance_page.status_code == status.HTTP_200_OK
        assert attendance_page.data['count'] == 4
        assert attendance_page.data['next'] is not None
        assert len(attendance_page.data['results']) == 2
        assert attendance_page.data['results'][0]['date'] == '2026-09-07'
        assert attendance_page.data['results'][0]['attendance_id'] is not None

        second_page = authenticated_client(student.user).get(attendance_url, {
            'date_from': '2026-09-01',
            'date_to': '2026-09-28',
            'page': 2,
            'page_size': 2,
        })
        assert second_page.status_code == status.HTTP_200_OK
        assert second_page.data['results'][-1] == {
            'attendance_id': None,
            'session_id': session.id,
            'date': '2026-09-28',
            'weekday': 'monday',
            'start_time': '15:30:00',
            'end_time': '16:30:00',
            'location': 'Room 204',
            'status': None,
        }

    def test_club_manager_sees_only_managed_memberships_and_other_user_is_denied(
        self, authenticated_client, academic_year
    ):
        student = StudentFactory(academic_year=academic_year)
        manager = ClubManagerFactory()
        managed = ClubFactory(
            manager=manager, academic_year=academic_year, status='active'
        )
        other = ClubFactory(academic_year=academic_year, status='active')
        managed.members.add(student)
        other.members.add(student)

        manager_response = authenticated_client(manager.user).get(
            reverse('achievement-api:student-clubs', kwargs={'student_id': student.id})
        )
        assert manager_response.status_code == status.HTTP_200_OK
        assert [row['id'] for row in manager_response.data['results']] == [managed.id]

        unrelated_student = StudentFactory(academic_year=academic_year)
        denied = authenticated_client(unrelated_student.user).get(
            reverse('achievement-api:student-clubs', kwargs={'student_id': student.id})
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_parent_sees_linked_child_attendance_but_not_another_student(
        self, authenticated_client, academic_year
    ):
        child = StudentFactory(academic_year=academic_year)
        other_student = StudentFactory(academic_year=academic_year)
        parent = ParentFactory()
        parent.students.add(child)
        club = ClubFactory(
            academic_year=academic_year,
            status='active',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
        )
        club.members.add(child, other_student)
        session = ClubSessionFactory(
            club=club,
            weekday='monday',
            start_time=time(15),
            end_time=time(16),
        )
        attendance = ClubAttendance.objects.create(
            session=session,
            student=child,
            date=date(2026, 9, 7),
            status='late',
        )
        client = authenticated_client(parent.user)

        response = client.get(reverse(
            'achievement-api:student-club-attendance',
            kwargs={'student_id': child.id, 'club_id': club.id},
        ), {
            'date_from': '2026-09-07',
            'date_to': '2026-09-07',
        })

        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 1
        assert response.data['results'][0] == {
            'attendance_id': attendance.id,
            'session_id': session.id,
            'date': '2026-09-07',
            'weekday': 'monday',
            'start_time': '15:00:00',
            'end_time': '16:00:00',
            'location': session.location,
            'status': 'late',
        }

        denied = client.get(reverse(
            'achievement-api:student-club-attendance',
            kwargs={'student_id': other_student.id, 'club_id': club.id},
        ))
        assert denied.status_code == status.HTTP_403_FORBIDDEN


class TestClubMembershipAndAttendance:
    @pytest.mark.parametrize('method', ['put', 'patch'])
    def test_attendance_id_updates_ignore_deleted_session_and_url_context(
        self, authenticated_client, admin_user, academic_year, method
    ):
        club = ClubFactory(academic_year=academic_year)
        session = ClubSessionFactory(club=club, weekday='monday')
        student = StudentFactory(academic_year=academic_year)
        club.members.add(student)
        attendance = ClubAttendance.objects.create(
            session=session,
            student=student,
            date=date(2026, 9, 7),
            status='present',
        )
        session.soft_delete(admin_user)
        client = authenticated_client(admin_user)
        url = reverse('achievement-api:club-attendance-detail', kwargs={
            'pk': club.id,
            'attendance_date': 'not-a-date',
            'session_id': 999999,
        })

        response = getattr(client, method)(url, {'records': [{
            'attendance_id': attendance.id,
            'student_id': student.id,
            'status': 'absent',
        }]}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['session_id'] == session.id
        assert response.data['date'] == '2026-09-07'
        attendance.refresh_from_db()
        assert attendance.status == 'absent'

    def test_member_removal_preserves_history_and_allows_updates(
        self, authenticated_client, admin_user, academic_year
    ):
        club = ClubFactory(
            academic_year=academic_year,
            start_date=date(2026, 9, 1), end_date=date(2027, 5, 31),
        )
        session = ClubSessionFactory(
            club=club, weekday='monday', start_time=time(15), end_time=time(16)
        )
        first = StudentFactory(academic_year=academic_year)
        second = StudentFactory(academic_year=academic_year)
        club.members.add(first)
        attendance = ClubAttendance.objects.create(
            session=session, student=first, date=date(2026, 9, 7), status='present'
        )
        client = authenticated_client(admin_user)

        replaced = client.put(
            reverse('achievement-api:club-members', kwargs={'pk': club.id}),
            {'student_ids': [second.id]},
            format='json',
        )
        assert replaced.status_code == status.HTTP_200_OK
        assert ClubAttendance.objects.filter(pk=attendance.id).exists()

        club.members.add(first)
        removed = client.delete(reverse(
            'achievement-api:club-member-delete',
            kwargs={'pk': club.id, 'student_id': first.id},
        ))
        assert removed.status_code == status.HTTP_200_OK
        assert ClubAttendance.objects.filter(pk=attendance.id).exists()

        updated = client.put(reverse(
            'achievement-api:club-attendance-detail',
            kwargs={
                'pk': club.id,
                'attendance_date': '2026-09-07',
                'session_id': session.id,
            },
        ), {'records': [
            {
                'attendance_id': attendance.id,
                'student_id': first.id,
                'status': 'absent',
            },
            {
                'attendance_id': None,
                'student_id': second.id,
                'status': 'present',
            },
        ]}, format='json')
        assert updated.status_code == status.HTTP_200_OK
        attendance.refresh_from_db()
        assert attendance.status == 'absent'
        assert ClubAttendance.objects.filter(
            session=session,
            student=second,
            date=date(2026, 9, 7),
            status='present',
        ).exists()

    def test_attendance_requires_every_current_member_and_returns_late_counts(
        self, authenticated_client, admin_user, academic_year
    ):
        club = ClubFactory(
            academic_year=academic_year,
            start_date=date(2026, 9, 1), end_date=date(2027, 5, 31),
        )
        session = ClubSessionFactory(
            club=club, weekday='monday', start_time=time(15), end_time=time(16)
        )
        first = StudentFactory(academic_year=academic_year)
        second = StudentFactory(academic_year=academic_year)
        club.members.add(first, second)
        client = authenticated_client(admin_user)
        url = reverse('achievement-api:club-attendance-detail', kwargs={
            'pk': club.id,
            'attendance_date': '2026-09-07',
            'session_id': session.id,
        })

        unrecorded = client.get(url)
        assert unrecorded.status_code == status.HTTP_200_OK
        assert all(
            record['attendance_id'] is None
            for record in unrecorded.data['records']
        )

        incomplete = client.put(url, {
            'records': [{
                'attendance_id': None,
                'student_id': first.id,
                'status': 'present',
            }]
        }, format='json')
        assert incomplete.status_code == status.HTTP_400_BAD_REQUEST

        response = client.put(url, {'records': [
            {'attendance_id': None, 'student_id': first.id, 'status': 'present'},
            {'attendance_id': None, 'student_id': second.id, 'status': 'late'},
        ]}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['present_count'] == 1
        assert response.data['late_count'] == 1
        assert response.data['absent_count'] == 0
        assert response.data['unmarked_count'] == 0
        assert all(
            record['attendance_id'] is not None
            for record in response.data['records']
        )

        first_record = next(
            record for record in response.data['records']
            if record['student_id'] == first.id
        )
        patched = client.patch(url, {'records': [{
            'attendance_id': first_record['attendance_id'],
            'student_id': first.id,
            'status': 'absent',
        }]}, format='json')
        assert patched.status_code == status.HTTP_200_OK
        patched_first = next(
            record for record in patched.data['records']
            if record['student_id'] == first.id
        )
        assert patched_first['attendance_id'] == first_record['attendance_id']
        assert patched_first['status'] == 'absent'

        history = client.get(reverse(
            'achievement-api:club-attendance-history', kwargs={'pk': club.id}
        ))
        assert history.status_code == status.HTTP_200_OK
        assert history.data['count'] == 1
        assert history.data['results'][0]['session_id'] == session.id

    def test_attendance_history_supports_year_month_and_pagination(
        self, authenticated_client, admin_user, academic_year
    ):
        club = ClubFactory(
            academic_year=academic_year,
            start_date=date(2026, 9, 1), end_date=date(2027, 5, 31),
        )
        session = ClubSessionFactory(
            club=club, weekday='monday', start_time=time(15), end_time=time(16)
        )
        student = StudentFactory(academic_year=academic_year)
        club.members.add(student)
        for attendance_date in (date(2026, 9, 7), date(2026, 9, 14), date(2026, 10, 5)):
            ClubAttendance.objects.create(
                session=session,
                student=student,
                date=attendance_date,
                status='present',
            )

        url = reverse('achievement-api:club-attendance-history', kwargs={'pk': club.id})
        response = authenticated_client(admin_user).get(url, {
            'year': 2026,
            'month': 9,
            'page': 1,
            'page_size': 1,
        })

        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 2
        assert response.data['previous'] is None
        assert response.data['next'] is not None
        assert len(response.data['results']) == 1
        assert response.data['results'][0]['date'] == '2026-09-14'

    @pytest.mark.parametrize(('parameter', 'value'), [
        ('year', 'invalid'),
        ('month', '13'),
    ])
    def test_attendance_history_rejects_invalid_year_or_month(
        self, authenticated_client, admin_user, academic_year, parameter, value
    ):
        club = ClubFactory(academic_year=academic_year)
        response = authenticated_client(admin_user).get(
            reverse('achievement-api:club-attendance-history', kwargs={'pk': club.id}),
            {parameter: value},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert parameter in response.data

    def test_available_students_uses_profile_ids_and_numeric_class_filter(
        self, authenticated_client, admin_user, academic_year, class_group,
        tmp_path, settings,
    ):
        settings.MEDIA_ROOT = tmp_path
        student = StudentFactory(
            academic_year=academic_year,
            user__first_name='Aruzhan',
            user__last_name='Sarsenova',
            user__avatar=SimpleUploadedFile('aruzhan.png', _valid_png_bytes(), 'image/png'),
        )
        EnrollmentFactory(
            student=student,
            class_group=class_group,
            academic_year=academic_year,
        )
        registered_student = StudentFactory(academic_year=academic_year)
        EnrollmentFactory(
            student=registered_student,
            class_group=class_group,
            academic_year=academic_year,
        )
        club = ClubFactory(academic_year=academic_year)
        club.members.add(registered_student)
        client = authenticated_client(admin_user)
        response = client.get(
            reverse('achievement-api:club-available-students'),
            {'club_id': club.id, 'class_group': class_group.id},
        )
        assert response.status_code == status.HTTP_200_OK
        result_ids = {result['id'] for result in response.data['results']}
        assert student.id in result_ids
        assert registered_student.id not in result_ids
        student_result = next(
            result for result in response.data['results'] if result['id'] == student.id
        )
        assert student_result['avatar'].startswith(
            'http://testserver/media/avatars/'
        )

    def test_available_students_requires_club_id(
        self, authenticated_client, admin_user
    ):
        response = authenticated_client(admin_user).get(
            reverse('achievement-api:club-available-students')
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['club_id'] == ['A numeric club ID is required.']


class TestClubAttachments:
    def test_upload_and_delete_attachment(
        self, authenticated_client, admin_user, academic_year, tmp_path, settings
    ):
        settings.MEDIA_ROOT = tmp_path
        club = ClubFactory(academic_year=academic_year)
        client = authenticated_client(admin_user)
        uploaded = SimpleUploadedFile(
            'plan.pdf', b'%PDF-1.4\nmock club plan', 'application/pdf'
        )
        response = client.post(
            reverse('achievement-api:club-attachment-upload', kwargs={'pk': club.id}),
            {'files': [uploaded]},
            format='multipart',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['attachments'][0]['file_type'] == 'document'
        assert response.data['attachments'][0]['url'].startswith(
            'http://testserver/media/'
        )
        attachment_id = response.data['attachments'][0]['id']
        attachment = Attachment.objects.get(pk=attachment_id)
        path = attachment.file.path

        deleted = client.delete(reverse(
            'achievement-api:club-attachment-delete',
            kwargs={'pk': club.id, 'attachment_id': attachment_id},
        ))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not Attachment.objects.filter(pk=attachment_id).exists()
        assert not __import__('pathlib').Path(path).exists()

    @pytest.mark.parametrize(('name', 'content', 'content_type', 'file_type'), [
        ('plan.pdf', b'%PDF-1.4\nmock', 'application/pdf', 'document'),
        ('photo.png', _valid_png_bytes(), 'image/png', 'image'),
    ])
    def test_supported_attachment_formats(
        self, authenticated_client, admin_user, academic_year,
        tmp_path, settings, name, content, content_type, file_type,
    ):
        settings.MEDIA_ROOT = tmp_path
        club = ClubFactory(academic_year=academic_year)
        response = authenticated_client(admin_user).post(
            reverse('achievement-api:club-attachment-upload', kwargs={'pk': club.id}),
            {'files': [SimpleUploadedFile(name, content, content_type)]},
            format='multipart',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['attachments'][0]['file_type'] == file_type

    @pytest.mark.parametrize(('name', 'content', 'expected_message'), [
        ('malware.exe', b'MZ executable', 'Unsupported file format'),
        ('word-document.doc', b'legacy Word document', 'Unsupported file format'),
        ('word-document.docx', b'Word document', 'Unsupported file format'),
        ('fake.png', b'not an image', 'invalid or corrupted'),
    ])
    def test_rejects_unsupported_or_spoofed_attachments(
        self, authenticated_client, admin_user, academic_year,
        name, content, expected_message,
    ):
        club = ClubFactory(academic_year=academic_year)
        response = authenticated_client(admin_user).post(
            reverse('achievement-api:club-attachment-upload', kwargs={'pk': club.id}),
            {'files': [SimpleUploadedFile(name, content)]},
            format='multipart',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_message in response.data['files'][0]
        assert Attachment.objects.count() == 0

    def test_rejects_attachment_over_10_mb(
        self, authenticated_client, admin_user, academic_year
    ):
        club = ClubFactory(academic_year=academic_year)
        uploaded = SimpleUploadedFile(
            'large.pdf',
            b'%PDF-' + b'x' * MAX_ATTACHMENT_SIZE_BYTES,
            'application/pdf',
        )
        response = authenticated_client(admin_user).post(
            reverse('achievement-api:club-attachment-upload', kwargs={'pk': club.id}),
            {'files': [uploaded]},
            format='multipart',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'must not exceed 10MB' in response.data['files'][0]
        assert Attachment.objects.count() == 0
