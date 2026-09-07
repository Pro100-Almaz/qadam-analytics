from datetime import date

from django.db.models import Count, Prefetch, Q, QuerySet
from django.shortcuts import get_object_or_404

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.achievement.models import Club, ClubAttendance, ClubSession
from apps.achievement.api.serializers import ClubSerializer, ClubStudentSerializer
from apps.authentication.models import Student
from apps.home.models import Enrollment
from core.error_messages import NO_ACCESS_STUDENT
from core.permissions import can_access_student, is_admin_role


def student_queryset() -> QuerySet:
    enrollments = Enrollment.objects.filter(status='active').select_related(
        'class_group__grade_level', 'academic_year'
    ).order_by('-academic_year__is_active', '-academic_year__year')
    return Student.objects.select_related('user').prefetch_related(
        Prefetch('enrollments', queryset=enrollments, to_attr='club_enrollments')
    )


def club_base_queryset(include_members=False) -> QuerySet:
    sessions = ClubSession.objects.order_by('weekday', 'start_time', 'id')
    qs = Club.objects.select_related(
        'academic_year', 'manager__user'
    ).prefetch_related(
        Prefetch('sessions', queryset=sessions, to_attr='active_club_sessions'),
        'attachments',
    ).annotate(
        member_count_value=Count('members', distinct=True),
        attendance_dates_count_value=Count(
            'sessions__attendances__date',
            filter=Q(
                sessions__attendances__is_deleted=False,
            ),
            distinct=True,
        ),
    )
    if include_members:
        qs = qs.prefetch_related(Prefetch(
            'members', queryset=student_queryset(), to_attr='prefetched_club_members'
        ))
    return qs


def club_queryset(user, include_members=False) -> QuerySet:
    qs = club_base_queryset(include_members=include_members)
    if not is_admin_role(user):
        qs = qs.filter(manager__user=user)
    return qs


def serialize_club(club, request, include_members=False):
    return ClubSerializer(
        club,
        context={'request': request, 'include_members': include_members},
    ).data


def student_club_queryset(user, student) -> QuerySet:
    student_attendance = Q(
        sessions__attendances__student=student,
        sessions__attendances__is_deleted=False,
    )
    clubs = club_base_queryset().filter(
        members=student,
        status='active',
    ).annotate(
        student_total_session_count=Count(
            'sessions__attendances', filter=student_attendance, distinct=True,
        ),
        student_present_count=Count(
            'sessions__attendances',
            filter=student_attendance & Q(sessions__attendances__status='present'),
            distinct=True,
        ),
        student_late_count=Count(
            'sessions__attendances',
            filter=student_attendance & Q(sessions__attendances__status='late'),
            distinct=True,
        ),
        student_absent_count=Count(
            'sessions__attendances',
            filter=student_attendance & Q(sessions__attendances__status='absent'),
            distinct=True,
        ),
    )
    if not can_access_student(user, student):
        clubs = clubs.filter(manager__user=user)
        if not clubs.exists():
            raise PermissionDenied(NO_ACCESS_STUDENT)
    return clubs


def parse_date(value, field='date'):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise serializers.ValidationError({field: ['Use YYYY-MM-DD format.']})


def attendance_session(club, session_id, allow_deleted=False):
    manager = ClubSession.all_objects if allow_deleted else ClubSession.objects
    return get_object_or_404(manager, pk=session_id, club=club)


def validate_attendance_date(club, session, attendance_date):
    if not club.start_date <= attendance_date <= club.end_date:
        raise serializers.ValidationError({
            'date': ['Attendance date must fall within the club date range.']
        })
    if attendance_date.strftime('%A').lower() != session.weekday:
        raise serializers.ValidationError({
            'date': [f'This session is scheduled for {session.weekday.capitalize()}.']
        })


def attendance_payload(club, session, attendance_date):
    attendances = list(ClubAttendance.objects.filter(
        session=session,
        date=attendance_date,
    ).select_related('student__user'))
    attendance_by_student = {row.student_id: row for row in attendances}
    current_ids = set(club.members.values_list('id', flat=True))
    student_ids = current_ids | set(attendance_by_student)
    students = student_queryset().filter(pk__in=student_ids).order_by(
        'user__first_name', 'user__last_name', 'id'
    )

    records = []
    counts = {'present': 0, 'absent': 0, 'late': 0}
    for student in students:
        attendance = attendance_by_student.get(student.id)
        attendance_status = attendance.status if attendance else None
        if attendance_status:
            counts[attendance_status] += 1
        brief = ClubStudentSerializer(student).data
        records.append({
            'attendance_id': attendance.id if attendance else None,
            'student_id': student.id,
            'full_name': brief['full_name'],
            'class_name': brief['class_name'],
            'status': attendance_status,
        })

    return {
        'club_id': club.id,
        'session_id': session.id,
        'date': attendance_date.isoformat(),
        'total_students': len(records),
        'present_count': counts['present'],
        'absent_count': counts['absent'],
        'late_count': counts['late'],
        'unmarked_count': len(records) - sum(counts.values()),
        'records': records,
    }
