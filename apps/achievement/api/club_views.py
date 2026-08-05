from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.achievement.models import (
    Attachment,
    Club,
    ClubAttendance,
    ClubSession,
    validate_attachment_format,
    validate_attachment_size,
)
from apps.achievement.api.services import (
    student_queryset,
    club_queryset,
    serialize_club,
    student_club_queryset,
    parse_date,
    attendance_session,
    validate_attendance_date,
    attendance_payload,
)
from apps.achievement.api.serializers import (
    ClubAttachmentSerializer,
    ClubAttendanceWriteSerializer,
    ClubMemberReplaceSerializer,
    ClubSerializer,
    ClubStudentSerializer,
    ClubWriteSerializer,
    StudentClubDetailSerializer,
    StudentClubSerializer,
)
from apps.achievement.api.views import _detect_file_type
from apps.authentication.models import Student
from core.permissions import IsClubManagementRole


class ClubPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ClubListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(
        responses=ClubSerializer(many=True),
        parameters=[
            OpenApiParameter('search', str),
            OpenApiParameter('academic_year', int),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request):
        clubs = club_queryset(request.user).order_by('-academic_year__year', 'start_date', 'name', 'id')
        search = request.query_params.get('search')
        if search:
            clubs = clubs.filter(name__icontains=search.strip())
        academic_year = request.query_params.get('academic_year')
        if academic_year:
            clubs = clubs.filter(academic_year_id=academic_year)

        paginator = ClubPagination()
        page = paginator.paginate_queryset(clubs, request, view=self)
        serializer = ClubSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(request=ClubWriteSerializer, responses={201: ClubSerializer})
    def post(self, request):
        serializer = ClubWriteSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        club = serializer.save()
        club = get_object_or_404(club_queryset(request.user), pk=club.pk)
        return Response(
            serialize_club(club, request),
            status=status.HTTP_201_CREATED,
        )


class StudentClubListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=StudentClubSerializer(many=True),
        parameters=[
            OpenApiParameter('academic_year', int),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, student_id):
        student = get_object_or_404(Student.objects.select_related('user'), pk=student_id)
        clubs = student_club_queryset(request.user, student)

        academic_year = request.query_params.get('academic_year')
        if academic_year:
            if not academic_year.isdigit():
                raise serializers.ValidationError({
                    'academic_year': ['A numeric academic year ID is required.']
                })
            clubs = clubs.filter(academic_year_id=int(academic_year))

        clubs = clubs.order_by('-academic_year__year', 'start_date', 'name', 'id')
        paginator = ClubPagination()
        page = paginator.paginate_queryset(clubs, request, view=self)
        data = StudentClubSerializer(
            page,
            many=True,
            context={'request': request, 'student': student},
        ).data
        return paginator.get_paginated_response(data)


class StudentClubDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=StudentClubDetailSerializer)
    def get(self, request, student_id, club_id):
        student = get_object_or_404(Student.objects.select_related('user'), pk=student_id)
        club = get_object_or_404(
            student_club_queryset(request.user, student),
            pk=club_id,
        )
        return Response(StudentClubDetailSerializer(
            club,
            context={'request': request, 'student': student},
        ).data)


class StudentClubAttendanceListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=OpenApiTypes.OBJECT,
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.DATE),
            OpenApiParameter('date_to', OpenApiTypes.DATE),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, student_id, club_id):
        student = get_object_or_404(Student.objects.select_related('user'), pk=student_id)
        club = get_object_or_404(
            student_club_queryset(request.user, student),
            pk=club_id,
        )
        date_from = (
            parse_date(request.query_params['date_from'], 'date_from')
            if request.query_params.get('date_from') else club.start_date
        )
        date_to = (
            parse_date(request.query_params['date_to'], 'date_to')
            if request.query_params.get('date_to') else club.end_date
        )
        if date_to < date_from:
            raise serializers.ValidationError({
                'date_to': ['date_to must be on or after date_from.']
            })

        range_start = max(date_from, club.start_date)
        range_end = min(date_to, club.end_date)
        results = []
        if range_start <= range_end:
            results = self._attendance_occurrences(
                club, student, range_start, range_end
            )

        paginator = ClubPagination()
        page = paginator.paginate_queryset(results, request, view=self)
        return paginator.get_paginated_response(page)

    @staticmethod
    def _attendance_occurrences(club, student, date_from, date_to):
        attendances = ClubAttendance.objects.filter(
            session__club=club,
            student=student,
            date__range=(date_from, date_to),
        ).select_related('session')
        attendance_by_occurrence = {
            (attendance.session_id, attendance.date): attendance
            for attendance in attendances
        }
        occurrences = {}
        weekday_numbers = {
            weekday: index
            for index, (weekday, _) in enumerate(ClubSession.WEEKDAY_CHOICES)
        }

        for session in club.active_club_sessions:
            days_until_session = (
                weekday_numbers[session.weekday] - date_from.weekday()
            ) % 7
            occurrence_date = date_from + timedelta(days=days_until_session)
            while occurrence_date <= date_to:
                attendance = attendance_by_occurrence.get(
                    (session.id, occurrence_date)
                )
                occurrences[(session.id, occurrence_date)] = (
                    StudentClubAttendanceListAPIView._attendance_row(
                        session, occurrence_date, attendance
                    )
                )
                occurrence_date += timedelta(days=7)

        for attendance in attendances:
            key = (attendance.session_id, attendance.date)
            occurrences.setdefault(
                key,
                StudentClubAttendanceListAPIView._attendance_row(
                    attendance.session, attendance.date, attendance
                ),
            )
        return [
            occurrences[key]
            for key in sorted(occurrences, key=lambda value: (value[1], value[0]))
        ]

    @staticmethod
    def _attendance_row(session, attendance_date, attendance):
        return {
            'attendance_id': attendance.id if attendance else None,
            'session_id': session.id,
            'date': attendance_date.isoformat(),
            'weekday': session.weekday,
            'start_time': session.start_time.isoformat(),
            'end_time': session.end_time.isoformat(),
            'location': session.location,
            'status': attendance.status if attendance else None,
        }


class ClubDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(responses=ClubSerializer)
    def get(self, request, pk):
        club = get_object_or_404(club_queryset(request.user, include_members=True), pk=pk)
        return Response(serialize_club(club, request, include_members=True))

    @extend_schema(request=ClubWriteSerializer, responses=ClubSerializer)
    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    @extend_schema(request=ClubWriteSerializer, responses=ClubSerializer)
    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        serializer = ClubWriteSerializer(
            club,
            data=request.data,
            partial=partial,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        club = get_object_or_404(club_queryset(request.user, include_members=True), pk=pk)
        return Response(serialize_club(club, request, include_members=True))

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request, pk):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        now = timezone.now()
        ClubAttendance.objects.filter(session__club=club).update(
            is_deleted=True,
            deleted_at=now,
            deleted_by=request.user,
        )
        ClubSession.objects.filter(club=club).update(
            is_deleted=True,
            deleted_at=now,
            deleted_by=request.user,
        )
        club.soft_delete(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClubAvailableStudentListAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(
        responses=ClubStudentSerializer(many=True),
        parameters=[
            OpenApiParameter('club_id', int, required=True),
            OpenApiParameter('search', str),
            OpenApiParameter('class_group', int),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request):
        club_id = request.query_params.get('club_id', '').strip()
        if not club_id.isdigit():
            raise serializers.ValidationError({
                'club_id': ['A numeric club ID is required.']
            })
        club = get_object_or_404(club_queryset(request.user), pk=int(club_id))
        students = student_queryset().filter(
            enrollments__status='active',
        ).exclude(
            clubs=club,
        ).distinct()

        search = request.query_params.get('search', '').strip()
        if search:
            students = students.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__username__icontains=search)
            )

        class_group = request.query_params.get('class_group')
        if class_group:
            if not class_group.isdigit():
                raise serializers.ValidationError({
                    'class_group': ['A numeric class group ID is required.']
                })
            students = students.filter(
                enrollments__class_group_id=int(class_group),
                enrollments__status='active',
            )

        paginator = ClubPagination()
        page = paginator.paginate_queryset(students.order_by(
            'user__first_name', 'user__last_name', 'id'
        ), request, view=self)
        data = ClubStudentSerializer(page, many=True, context={'request': request}).data
        response = paginator.get_paginated_response(data)
        response.data.pop('next', None)
        response.data.pop('previous', None)
        return response


class ClubMemberListReplaceAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(responses=ClubStudentSerializer(many=True))
    def get(self, request, pk):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        members = student_queryset().filter(clubs=club).order_by(
            'user__first_name', 'user__last_name', 'id'
        )
        data = ClubStudentSerializer(members, many=True, context={'request': request}).data
        return Response({'count': len(data), 'results': data})

    @extend_schema(request=ClubMemberReplaceSerializer, responses=OpenApiTypes.OBJECT)
    @transaction.atomic
    def put(self, request, pk):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        serializer = ClubMemberReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student_ids = serializer.validated_data['student_ids']
        club.members.set(Student.objects.filter(pk__in=student_ids))
        members = student_queryset().filter(pk__in=student_ids).order_by(
            'user__first_name', 'user__last_name', 'id'
        )
        data = ClubStudentSerializer(members, many=True, context={'request': request}).data
        return Response({
            'club_id': club.id,
            'member_count': len(data),
            'members': data,
        })


class ClubMemberDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @transaction.atomic
    def delete(self, request, pk, student_id):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        if not club.members.filter(pk=student_id).exists():
            return Response(
                {'detail': 'Student is not registered in this club.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        club.members.remove(student_id)
        return Response({
            'detail': 'Student removed from club.',
            'club_id': club.id,
            'student_id': student_id,
            'member_count': club.members.count(),
        })


class ClubAttendanceHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(
        responses=OpenApiTypes.OBJECT,
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.DATE),
            OpenApiParameter('date_to', OpenApiTypes.DATE),
            OpenApiParameter('year', int),
            OpenApiParameter('month', int),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, pk):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        attendances = ClubAttendance.objects.filter(
            session__club=club,
        ).select_related('session')

        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        if date_from:
            attendances = attendances.filter(date__gte=parse_date(date_from, 'date_from'))
        if date_to:
            attendances = attendances.filter(date__lte=parse_date(date_to, 'date_to'))
        if date_from and date_to and parse_date(date_to) < parse_date(date_from):
            raise serializers.ValidationError({
                'date_to': ['date_to must be on or after date_from.']
            })

        year = request.query_params.get('year')
        if year:
            if not year.isdigit() or not 1 <= int(year) <= 9999:
                raise serializers.ValidationError({
                    'year': ['Year must be an integer between 1 and 9999.']
                })
            attendances = attendances.filter(date__year=int(year))

        month = request.query_params.get('month')
        if month:
            if not month.isdigit() or not 1 <= int(month) <= 12:
                raise serializers.ValidationError({
                    'month': ['Month must be an integer between 1 and 12.']
                })
            attendances = attendances.filter(date__month=int(month))

        keys = list(attendances.values_list('session_id', 'date').distinct().order_by(
            '-date', 'session_id'
        ))
        paginator = ClubPagination()
        page = paginator.paginate_queryset(keys, request, view=self)
        results = []
        for session_id, attendance_date in page:
            session = ClubSession.all_objects.get(pk=session_id)
            payload = attendance_payload(club, session, attendance_date)
            payload.pop('records')
            payload.update({
                'weekday': session.weekday,
                'start_time': session.start_time.strftime('%H:%M'),
                'end_time': session.end_time.strftime('%H:%M'),
                'location': session.location,
            })
            results.append(payload)
        return paginator.get_paginated_response(results)


class ClubAttendanceDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk, attendance_date, session_id):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        parsed_date = parse_date(attendance_date)
        session = attendance_session(club, session_id, allow_deleted=True)
        if session.is_deleted and not ClubAttendance.objects.filter(
            session=session, date=parsed_date
        ).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)
        validate_attendance_date(club, session, parsed_date)
        return Response(attendance_payload(club, session, parsed_date))

    @extend_schema(request=ClubAttendanceWriteSerializer, responses=OpenApiTypes.OBJECT)
    def put(self, request, pk, attendance_date, session_id):
        return self._write(request, pk, attendance_date, session_id, partial=False)

    @extend_schema(request=ClubAttendanceWriteSerializer, responses=OpenApiTypes.OBJECT)
    def patch(self, request, pk, attendance_date, session_id):
        return self._write(request, pk, attendance_date, session_id, partial=True)

    @transaction.atomic
    def _write(self, request, pk, attendance_date, session_id, partial):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        serializer = ClubAttendanceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data['records']

        if all(row.get('attendance_id') is not None for row in rows):
            return self._update_by_attendance_ids(club, rows)

        parsed_date = parse_date(attendance_date)
        session = attendance_session(club, session_id)
        validate_attendance_date(club, session, parsed_date)
        expected_student_ids = set(club.members.values_list('id', flat=True))
        expected_student_ids.update(ClubAttendance.objects.filter(
            session=session,
            date=parsed_date,
        ).values_list('student_id', flat=True))
        serializer = ClubAttendanceWriteSerializer(
            data=request.data,
            context={
                'expected_student_ids': expected_student_ids,
                'require_complete': not partial,
            },
        )
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data['records']
        return self._write_occurrence(club, session, parsed_date, rows)

    @staticmethod
    def _update_by_attendance_ids(club, rows):
        attendance_ids = {
            row['attendance_id'] for row in rows
        }
        attendances_by_id = ClubAttendance.objects.select_for_update().select_related(
            'session'
        ).filter(
            pk__in=attendance_ids,
        ).in_bulk()
        missing_ids = sorted(attendance_ids - set(attendances_by_id))
        if missing_ids:
            raise serializers.ValidationError({
                'records': [f'Unknown attendance IDs: {missing_ids}.']
            })

        if any(
            attendance.session.club_id != club.id
            for attendance in attendances_by_id.values()
        ):
            raise serializers.ValidationError({
                'records': ['All attendance IDs must belong to the requested club.']
            })

        occurrences = {
            (attendance.session_id, attendance.date)
            for attendance in attendances_by_id.values()
        }
        if len(occurrences) != 1:
            raise serializers.ValidationError({
                'records': [
                    'All attendance IDs in one request must belong to the same session date.'
                ]
            })

        for row in rows:
            attendance_id = row['attendance_id']
            attendance = attendances_by_id[attendance_id]
            if attendance.student_id != row['student_id']:
                raise serializers.ValidationError({
                    'records': [
                        f'Attendance ID {attendance_id} does not belong to student '
                        f"{row['student_id']}."
                    ]
                })
            attendance.status = row['status']
            attendance.save(update_fields=['status', 'updated_at'])

        first_attendance = next(iter(attendances_by_id.values()))
        return Response(attendance_payload(
            club,
            first_attendance.session,
            first_attendance.date,
        ))

    @staticmethod
    def _write_occurrence(club, session, parsed_date, rows):
        attendance_ids = {
            row['attendance_id'] for row in rows if row.get('attendance_id') is not None
        }
        attendances_by_id = ClubAttendance.objects.select_for_update().filter(
            pk__in=attendance_ids,
            session__club=club,
        ).in_bulk()
        missing_ids = sorted(attendance_ids - set(attendances_by_id))
        if missing_ids:
            raise serializers.ValidationError({
                'records': [f'Unknown attendance IDs for this club: {missing_ids}.']
            })

        for row in rows:
            attendance_id = row.get('attendance_id')
            if attendance_id is not None:
                attendance = attendances_by_id[attendance_id]
                if attendance.session_id != session.id or attendance.date != parsed_date:
                    raise serializers.ValidationError({
                        'records': [
                            f'Attendance ID {attendance_id} does not belong to this '
                            'session and date.'
                        ]
                    })
                if attendance.student_id != row['student_id']:
                    raise serializers.ValidationError({
                        'records': [
                            f'Attendance ID {attendance_id} does not belong to student '
                            f"{row['student_id']}."
                        ]
                    })
                attendance.status = row['status']
                attendance.save(update_fields=['status', 'updated_at'])
                continue

            if ClubAttendance.objects.filter(
                session=session,
                student_id=row['student_id'],
                date=parsed_date,
            ).exists():
                raise serializers.ValidationError({
                    'records': [
                        f"attendance_id is required for student {row['student_id']} "
                        'because attendance already exists.'
                    ]
                })
            ClubAttendance.objects.create(
                session=session,
                student_id=row['student_id'],
                date=parsed_date,
                status=row['status'],
            )
        return Response(attendance_payload(club, session, parsed_date))


class ClubAttachmentUploadAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(request=OpenApiTypes.BINARY, responses={201: OpenApiTypes.OBJECT})
    def post(self, request, pk):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        if not files:
            raise serializers.ValidationError({
                'files': ['No files provided. Use the files field.']
            })
        for uploaded_file in files:
            try:
                validate_attachment_size(uploaded_file)
                validate_attachment_format(uploaded_file)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'files': exc.messages})

        content_type = ContentType.objects.get_for_model(Club)
        created = []
        with transaction.atomic():
            for uploaded_file in files:
                created.append(Attachment.objects.create(
                    content_type=content_type,
                    object_id=club.id,
                    file=uploaded_file,
                    file_type=_detect_file_type(uploaded_file.name),
                    original_name=uploaded_file.name,
                    uploaded_by=request.user,
                ))
        return Response(
            {
                'attachments': ClubAttachmentSerializer(
                    created,
                    many=True,
                    context={'request': request},
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ClubAttachmentDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated, IsClubManagementRole]

    @extend_schema(responses={204: None})
    def delete(self, request, pk, attachment_id):
        club = get_object_or_404(club_queryset(request.user), pk=pk)
        content_type = ContentType.objects.get_for_model(Club)
        attachment = get_object_or_404(
            Attachment,
            pk=attachment_id,
            content_type=content_type,
            object_id=club.id,
        )
        attachment.file.delete(save=False)
        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
