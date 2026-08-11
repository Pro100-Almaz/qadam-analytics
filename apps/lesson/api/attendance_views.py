"""
CRUD endpoints for subject schedules, their weekly sessions and attendance.

Write access follows the same rules everywhere in this module:
- Admin / Supervisor / Principal — any subject, any class group
- Teacher                       — only offerings they are assigned to
- HomeroomTeacher               — any subject taught to their homeroom class
Students and parents get read-only access to their own (or their children's)
schedules and attendance — except for the per-session attendance list, which
students cannot read at all.
"""

from django.db.models import Min, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Parent, Student, Teacher
from apps.home.models import Enrollment, TeachingAssignment
from apps.lesson.models import ScheduleAttendance, ScheduleSession, SubjectSchedule
from core.error_messages import NO_PERMISSION, OWN_OFFERINGS_ONLY
from apps.lesson.services import build_other_sessions_map
from core.permissions import (
    IsNotStudent,
    IsTeacherAdminOrSupervisor,
    can_manage_offering_schedule,
    is_admin_role,
    is_teacher_role,
    teacher_homeroom_class_group_ids,
)

from .serializers import (
    ScheduleAttendanceSerializer,
    ScheduleAttendanceWriteSerializer,
    ScheduleSessionSerializer,
    ScheduleSessionWriteSerializer,
    SubjectScheduleSerializer,
    SubjectScheduleWriteSerializer,
    TeachingAssignmentListSerializer,
)


class SchedulePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


# ── Queryset scoping ──


class CustomQueryset:
    @classmethod
    def schedule_queryset(cls, user):
        """SubjectSchedules visible to the requesting user."""
        qs = SubjectSchedule.objects.select_related(
            'offering', 'offering__subject',
            'offering__class_group', 'offering__academic_year',
        ).prefetch_related('sessions')

        return cls._filter_qs_by_roles(qs, user)

    @classmethod
    def teaching_assignment_queryset(cls, user):
        """TeachingAssignments visible to the requesting user — same rules as schedules."""
        qs = TeachingAssignment.objects.select_related(
            'teacher', 'teacher__user',
            'offering', 'offering__subject',
            'offering__class_group', 'offering__class_group__grade_level',
            'offering__academic_year',
        )

        return cls._filter_qs_by_roles(qs, user)

    @staticmethod
    def _filter_qs_by_roles(qs, user):
        if is_admin_role(user):
            return qs

        if is_teacher_role(user):
            teacher = Teacher.objects.filter(user=user).first()
            if teacher is None:
                return qs.none()
            return qs.filter(teacher_offering_filter(teacher))

        if user.is_student():
            student = Student.objects.filter(user=user).first()
            if student is None:
                return qs.none()
            return qs.filter(
                offering__class_group_id__in=active_class_group_ids([student])
            )

        if user.is_parent():
            parent = Parent.objects.filter(user=user).first()
            if parent is None:
                return qs.none()
            return qs.filter(
                offering__class_group_id__in=active_class_group_ids(parent.students.all())
            )

        return qs.none()


def active_class_group_ids(students):
    return Enrollment.objects.filter(
        student__in=students, status='active',
    ).values_list('class_group_id', flat=True)


def teacher_offering_filter(teacher):
    """Offerings a teacher may see: their own subjects + their homeroom class."""
    offering_ids = TeachingAssignment.objects.filter(
        teacher=teacher
    ).values_list('offering_id', flat=True)
    homeroom_ids = teacher_homeroom_class_group_ids(teacher)
    return Q(offering_id__in=offering_ids) | Q(offering__class_group_id__in=homeroom_ids)


def session_queryset(user):
    """ScheduleSessions belonging to schedules the user can see."""
    return ScheduleSession.objects.filter(
        schedule__in=CustomQueryset.schedule_queryset(user).values('id')
    ).select_related(
        'schedule', 'schedule__offering', 'schedule__offering__subject',
        'schedule__offering__class_group',
    )


def attendance_queryset(user):
    """
    Attendance rows visible to the requesting user.

    Staff see every student in the schedules they can access; students see only
    their own rows and parents only their children's.
    """
    qs = ScheduleAttendance.objects.select_related(
        'student', 'student__user', 'session', 'session__schedule',
        'session__schedule__offering', 'session__schedule__offering__subject',
        'session__schedule__offering__class_group',
    )

    if is_admin_role(user) or is_teacher_role(user):
        return qs.filter(session__in=session_queryset(user).values('id'))

    if user.is_student():
        student = Student.objects.filter(user=user).first()
        if student is None:
            return qs.none()
        return qs.filter(student=student)

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        return qs.filter(student__in=parent.students.all())

    return qs.none()


def session_attendance_queryset(user):
    """
    Attendance rows for the per-session list, unscoped by offering.

    Unlike attendance_queryset() this does not restrict staff and teachers to
    the offerings they own — any session is readable, whoever teaches it.
    Parents stay limited to their own children; students never reach this
    (IsNotStudent gates the endpoint).
    """
    qs = ScheduleAttendance.objects.select_related(
        'student', 'student__user', 'session', 'session__schedule',
        'session__schedule__offering', 'session__schedule__offering__subject',
        'session__schedule__offering__class_group',
    )

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        return qs.filter(student__in=parent.students.all())

    return qs


# ── Teaching assignments ──

class TeachingAssignmentListAPIView(APIView):
    """
    GET teaching-assignments/ — offerings of active subjects with their teacher.

    One row per offering, carrying its primary teacher. Offerings with several
    primary teachers collapse to the earliest assignment; offerings with no
    primary teacher at all are left out.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=TeachingAssignmentListSerializer(many=True),
        parameters=[
            OpenApiParameter('academic_year', int),
            OpenApiParameter('class_group', int),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request):
        rows = CustomQueryset.teaching_assignment_queryset(request.user).filter(
            role='primary',
            offering__subject__status='active',
        )

        params = request.query_params
        if params.get('academic_year'):
            rows = rows.filter(offering__academic_year_id=params['academic_year'])
        if params.get('class_group'):
            rows = rows.filter(offering__class_group_id=params['class_group'])

        # Collapse to one row per offering, keeping the earliest assignment.
        first_ids = (
            rows.order_by()
            .values('offering_id')
            .annotate(first_id=Min('id'))
            .values_list('first_id', flat=True)
        )
        rows = rows.filter(id__in=first_ids).order_by(
            'offering__subject__name', 'offering__class_group_id',
        )

        paginator = SchedulePagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = TeachingAssignmentListSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)


# ── Subject schedules ──

class SubjectScheduleListCreateAPIView(APIView):
    """
    GET  subject-schedules/   — list schedules visible to the user
    POST subject-schedules/   — create a schedule for an offering
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    @extend_schema(
        responses=SubjectScheduleSerializer(many=True),
        parameters=[
            OpenApiParameter('offering', int),
            OpenApiParameter('quarter', int),
            OpenApiParameter('class_group', int),
            OpenApiParameter('subject', int),
            OpenApiParameter('academic_year', int),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request):
        schedules = CustomQueryset.schedule_queryset(request.user)

        params = request.query_params
        if params.get('offering'):
            schedules = schedules.filter(offering_id=params['offering'])
        if params.get('quarter'):
            schedules = schedules.filter(quarter=params['quarter'])
        if params.get('class_group'):
            schedules = schedules.filter(offering__class_group_id=params['class_group'])
        if params.get('subject'):
            schedules = schedules.filter(offering__subject_id=params['subject'])
        if params.get('academic_year'):
            schedules = schedules.filter(
                offering__academic_year_id=params['academic_year']
            )

        schedules = schedules.order_by(
            'offering__class_group_id', 'offering__subject__name', 'quarter',
        )

        paginator = SchedulePagination()
        page = paginator.paginate_queryset(schedules, request, view=self)
        serializer = SubjectScheduleSerializer(
            page,
            many=True,
            context={
                'request': request,
                'other_sessions_map': build_other_sessions_map(page),
            },
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=SubjectScheduleWriteSerializer,
        responses={201: SubjectScheduleSerializer},
    )
    def post(self, request):
        serializer = SubjectScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        offering = serializer.validated_data['offering']
        if not can_manage_offering_schedule(request.user, offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        schedule = serializer.save()
        return Response(
            SubjectScheduleSerializer(schedule, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class SubjectScheduleDetailAPIView(APIView):
    """
    GET    subject-schedules/<pk>/  — schedule with its sessions
    PATCH  subject-schedules/<pk>/  — update offering / quarter
    DELETE subject-schedules/<pk>/  — delete schedule (cascades to sessions)
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]

    @extend_schema(responses=SubjectScheduleSerializer)
    def get(self, request, pk):
        schedule = get_object_or_404(CustomQueryset.schedule_queryset(request.user), pk=pk)
        return Response(
            SubjectScheduleSerializer(schedule, context={'request': request}).data
        )

    @extend_schema(
        request=SubjectScheduleWriteSerializer,
        responses=SubjectScheduleSerializer,
    )
    def patch(self, request, pk):
        schedule = get_object_or_404(
            SubjectSchedule.objects.select_related('offering'), pk=pk
        )
        if not can_manage_offering_schedule(request.user, schedule.offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        serializer = SubjectScheduleWriteSerializer(
            schedule, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)

        # Moving a schedule to another offering requires rights on the target too.
        target_offering = serializer.validated_data.get('offering')
        if target_offering and not can_manage_offering_schedule(
            request.user, target_offering
        ):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        schedule = serializer.save()
        schedule = get_object_or_404(CustomQueryset.schedule_queryset(request.user), pk=schedule.pk)
        return Response(
            SubjectScheduleSerializer(schedule, context={'request': request}).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        schedule = get_object_or_404(
            SubjectSchedule.objects.select_related('offering'), pk=pk
        )
        if not can_manage_offering_schedule(request.user, schedule.offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        schedule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Schedule sessions ──

class ScheduleSessionListCreateAPIView(APIView):
    """
    GET  subject-schedules/<schedule_id>/sessions/   — weekly slots of a schedule
    POST subject-schedules/<schedule_id>/sessions/   — add a slot
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    @extend_schema(responses=ScheduleSessionSerializer(many=True))
    def get(self, request, schedule_id):
        schedule = get_object_or_404(CustomQueryset.schedule_queryset(request.user), pk=schedule_id)
        sessions = schedule.sessions.order_by('weekday', 'order')
        return Response(ScheduleSessionSerializer(sessions, many=True).data)

    @extend_schema(
        request=ScheduleSessionWriteSerializer,
        responses={201: ScheduleSessionSerializer},
    )
    def post(self, request, schedule_id):
        schedule = get_object_or_404(
            SubjectSchedule.objects.select_related('offering'), pk=schedule_id
        )
        if not can_manage_offering_schedule(request.user, schedule.offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        serializer = ScheduleSessionWriteSerializer(
            data=request.data, context={'request': request, 'schedule': schedule},
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save(schedule=schedule)

        return Response(
            ScheduleSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


class ScheduleSessionDetailAPIView(APIView):
    """
    GET    schedule-sessions/<pk>/  — single slot
    PATCH  schedule-sessions/<pk>/  — change weekday / order
    DELETE schedule-sessions/<pk>/  — delete slot (cascades to its attendance)
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]

    @extend_schema(responses=ScheduleSessionSerializer)
    def get(self, request, pk):
        session = get_object_or_404(session_queryset(request.user), pk=pk)
        return Response(ScheduleSessionSerializer(session).data)

    @extend_schema(
        request=ScheduleSessionWriteSerializer,
        responses=ScheduleSessionSerializer,
    )
    def patch(self, request, pk):
        session = get_object_or_404(
            ScheduleSession.objects.select_related('schedule', 'schedule__offering'),
            pk=pk,
        )
        if not can_manage_offering_schedule(request.user, session.schedule.offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        serializer = ScheduleSessionWriteSerializer(
            session,
            data=request.data,
            partial=True,
            context={'request': request, 'schedule': session.schedule},
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save()

        return Response(ScheduleSessionSerializer(session).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        session = get_object_or_404(
            ScheduleSession.objects.select_related('schedule', 'schedule__offering'),
            pk=pk,
        )
        if not can_manage_offering_schedule(request.user, session.schedule.offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Attendance ──

class ScheduleAttendanceListCreateAPIView(APIView):
    """
    GET  schedule-sessions/<session_id>/attendance/  — attendance rows for a slot
    POST schedule-sessions/<session_id>/attendance/  — record one student's attendance

    Students are shut out of the list entirely; they read their own attendance
    through students/<student_id>/attendance/ instead.

    GET reads any session regardless of who teaches the offering; POST still
    requires rights on that offering.
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated(), IsNotStudent()]

    @extend_schema(
        responses=ScheduleAttendanceSerializer(many=True),
        parameters=[
            OpenApiParameter('date', OpenApiTypes.DATE),
            OpenApiParameter('date_from', OpenApiTypes.DATE),
            OpenApiParameter('date_to', OpenApiTypes.DATE),
            OpenApiParameter('student', int),
            OpenApiParameter('status', str),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, session_id):
        # Readable for any session, not just the caller's own offerings, so a
        # 404 here means the session genuinely does not exist.
        get_object_or_404(ScheduleSession, pk=session_id)

        rows = session_attendance_queryset(request.user).filter(session_id=session_id)

        params = request.query_params
        if params.get('date'):
            rows = rows.filter(date=params['date'])
        if params.get('date_from'):
            rows = rows.filter(date__gte=params['date_from'])
        if params.get('date_to'):
            rows = rows.filter(date__lte=params['date_to'])
        if params.get('student'):
            rows = rows.filter(student_id=params['student'])
        if params.get('status'):
            rows = rows.filter(status=params['status'])

        rows = rows.order_by('-date', 'student__user__last_name', 'student_id')

        paginator = SchedulePagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = ScheduleAttendanceSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=ScheduleAttendanceWriteSerializer,
        responses={201: ScheduleAttendanceSerializer},
    )
    def post(self, request, session_id):
        session = get_object_or_404(
            ScheduleSession.objects.select_related('schedule', 'schedule__offering'),
            pk=session_id,
        )
        if not can_manage_offering_schedule(request.user, session.schedule.offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)

        serializer = ScheduleAttendanceWriteSerializer(
            data=request.data, context={'request': request, 'session': session},
        )
        serializer.is_valid(raise_exception=True)
        attendance = serializer.save(session=session)

        return Response(
            ScheduleAttendanceSerializer(
                attendance, context={'request': request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ScheduleAttendanceDetailAPIView(APIView):
    """
    GET    attendance/<pk>/  — single attendance row
    PATCH  attendance/<pk>/  — change status / date / student
    DELETE attendance/<pk>/  — remove the row
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]

    @extend_schema(responses=ScheduleAttendanceSerializer)
    def get(self, request, pk):
        attendance = get_object_or_404(attendance_queryset(request.user), pk=pk)
        return Response(
            ScheduleAttendanceSerializer(
                attendance, context={'request': request},
            ).data
        )

    @extend_schema(
        request=ScheduleAttendanceWriteSerializer,
        responses=ScheduleAttendanceSerializer,
    )
    def patch(self, request, pk):
        attendance = self._get_writable(request, pk)
        if isinstance(attendance, Response):
            return attendance

        serializer = ScheduleAttendanceWriteSerializer(
            attendance,
            data=request.data,
            partial=True,
            context={'request': request, 'session': attendance.session},
        )
        serializer.is_valid(raise_exception=True)
        attendance = serializer.save()

        return Response(
            ScheduleAttendanceSerializer(
                attendance, context={'request': request},
            ).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        attendance = self._get_writable(request, pk)
        if isinstance(attendance, Response):
            return attendance

        attendance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, pk):
        attendance = get_object_or_404(
            ScheduleAttendance.objects.select_related(
                'session', 'session__schedule', 'session__schedule__offering',
            ),
            pk=pk,
        )
        offering = attendance.session.schedule.offering
        if not can_manage_offering_schedule(request.user, offering):
            return Response({'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN)
        return attendance


class StudentAttendanceListAPIView(APIView):
    """GET students/<student_id>/attendance/ — one student's attendance history."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=ScheduleAttendanceSerializer(many=True),
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.DATE),
            OpenApiParameter('date_to', OpenApiTypes.DATE),
            OpenApiParameter('offering', int),
            OpenApiParameter('quarter', int),
            OpenApiParameter('status', str),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, student_id):
        from core.permissions import can_access_student

        student = get_object_or_404(
            Student.objects.select_related('user'), pk=student_id
        )
        if not can_access_student(request.user, student):
            return Response({'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN)


        rows = attendance_queryset(request.user).filter(student=student)

        params = request.query_params
        if params.get('date_from'):
            rows = rows.filter(date__gte=params['date_from'])
        if params.get('date_to'):
            rows = rows.filter(date__lte=params['date_to'])
        if params.get('offering'):
            rows = rows.filter(session__schedule__offering_id=params['offering'])
        if params.get('quarter'):
            rows = rows.filter(session__schedule__quarter=params['quarter'])
        if params.get('status'):
            rows = rows.filter(status=params['status'])

        rows = rows.order_by('-date', 'session__order')

        paginator = SchedulePagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = ScheduleAttendanceSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)
