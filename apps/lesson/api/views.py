from django.db import models as django_models
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student, Teacher, Parent
from apps.home.models import SubjectOffering, Enrollment, TeachingAssignment
from apps.lesson.models import Lesson, Topic, TopicGrade, MergedLessonComment, QuarterGradeSnapshot
from core.permissions import (
    can_access_lesson, can_modify_lesson, can_grade_student,
    is_admin_role, is_teacher_role,
)
from core.error_messages import (
    OWN_OFFERINGS_ONLY, NO_VIEW_LESSON, NO_TOPICS_FOUND, NOT_A_SUBTOPIC,
)
from apps.lesson.services import (
    get_available_offerings,
    build_graded_percent_map,
    recalculate_topic_weights,
    distribute_subtopic_weights,
    submit_grades,
    delete_student_grades,
    freeze_quarter_grades,
)

from .permissions import IsTeacherAdminOrSupervisor
from .serializers import (
    LessonListSerializer,
    LessonDetailSerializer,
    LessonCreateSerializer,
    TopicCreateSerializer,
    TopicUpdateSerializer,
    SubtopicCreateSerializer,
    SubtopicUpdateSerializer,
    GradingDataSerializer,
    GradeSubmitSerializer,
    CalendarLessonSerializer,
)


# ── Lessons ──

class LessonListCreateAPIView(APIView):
    """
    GET  lessons/   — list lessons with optional filters
    POST lessons/   — create a lesson
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    def get(self, request):
        class_group_id = request.query_params.get('class_group')
        subject_name = request.query_params.get('subject')
        quarter = request.query_params.get('quarter')

        lessons = Lesson.objects.select_related(
            'offering', 'offering__subject', 'offering__class_group',
            'offering__academic_year',
        )

        user = request.user
        if is_admin_role(user):
            pass
        elif is_teacher_role(user):
            try:
                teacher = Teacher.objects.get(user=user)
                offering_ids = TeachingAssignment.objects.filter(
                    teacher=teacher
                ).values_list('offering_id', flat=True)
                lessons = lessons.filter(offering_id__in=offering_ids)
            except Teacher.DoesNotExist:
                lessons = lessons.none()
        elif user.is_parent():
            try:
                parent = Parent.objects.get(user=user)
                children = parent.students.all()
                class_group_ids = Enrollment.objects.filter(
                    student__in=children, status='active',
                ).values_list('class_group_id', flat=True)
                lessons = lessons.filter(
                    offering__class_group_id__in=class_group_ids
                )
            except Parent.DoesNotExist:
                lessons = lessons.none()
        elif user.is_student():
            try:
                student = Student.objects.get(user=user)
                class_group_ids = Enrollment.objects.filter(
                    student=student, status='active',
                ).values_list('class_group_id', flat=True)
                lessons = lessons.filter(
                    offering__class_group_id__in=class_group_ids
                )
            except Student.DoesNotExist:
                lessons = lessons.none()
        else:
            lessons = lessons.none()

        if class_group_id and class_group_id != 'all':
            lessons = lessons.filter(offering__class_group_id=class_group_id)
        if subject_name and subject_name != 'all':
            lessons = lessons.filter(offering__subject__name=subject_name)
        if quarter and quarter != 'all':
            lessons = lessons.filter(quarter=quarter)

        lessons = list(lessons)
        graded_percent_map = build_graded_percent_map(lessons)

        serializer = LessonListSerializer(
            lessons,
            many=True,
            context={'request': request, 'graded_percent_map': graded_percent_map},
        )
        return Response(serializer.data)

    def post(self, request):
        serializer = LessonCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        offering = serializer.validated_data['offering']
        available = get_available_offerings(request.user)
        if not available.filter(id=offering.id).exists():
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        lesson = serializer.save()
        return Response(
            LessonDetailSerializer(lesson, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class LessonDetailDeleteAPIView(APIView):
    """
    GET    lessons/<id>/  — lesson detail
    DELETE lessons/<id>/  — delete lesson
    """

    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    def get(self, request, pk):
        lesson = get_object_or_404(
            Lesson.objects.select_related(
                'offering', 'offering__subject',
                'offering__class_group', 'offering__academic_year',
            ),
            pk=pk,
        )
        if not can_access_lesson(request.user, lesson):
            return Response(
                {'detail': NO_VIEW_LESSON},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = LessonDetailSerializer(lesson, context={'request': request})
        return Response(serializer.data)

    def delete(self, request, pk):
        lesson = get_object_or_404(Lesson, pk=pk)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )
        lesson.soft_delete(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Topics ──

class TopicCreateAPIView(APIView):
    """POST lessons/<lesson_id>/topics/ — create a parent topic."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TopicCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        max_order = Topic.objects.filter(
            lesson=lesson, parent__isnull=True
        ).aggregate(max_order=django_models.Max('order'))['max_order'] or 0

        topic = Topic.objects.create(
            lesson=lesson,
            parent=None,
            title=data['title'],
            comment_template=data.get('comment_template', ''),
            order=max_order + 1,
            weight=0,
        )

        recalculate_topic_weights(lesson)
        topic.refresh_from_db()

        from .serializers import TopicSerializer
        return Response(
            TopicSerializer(topic).data,
            status=status.HTTP_201_CREATED,
        )


class TopicUpdateDeleteAPIView(APIView):
    """
    PATCH  topics/<id>/  — update topic
    DELETE topics/<id>/  — delete topic and rebalance weights
    """
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def patch(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk)
        lesson = topic.lesson
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TopicUpdateSerializer(topic, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        from .serializers import TopicSerializer
        # Re-fetch with subtopics
        topic.refresh_from_db()
        return Response(TopicSerializer(topic).data)

    def delete(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk)
        lesson = topic.lesson
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        lesson_id = lesson.id
        topic.soft_delete(request.user)

        lesson = get_object_or_404(Lesson, pk=lesson_id)
        recalculate_topic_weights(lesson)
        distribute_subtopic_weights(lesson)

        return Response(status=status.HTTP_204_NO_CONTENT)


class TopicDistributeWeightsAPIView(APIView):
    """POST lessons/<lesson_id>/topics/distribute-weights/ — equal weight distribution."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)
        if not topics.exists():
            return Response(
                {'detail': NO_TOPICS_FOUND},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recalculate_topic_weights(lesson)

        from .serializers import TopicSerializer
        updated = Topic.objects.filter(lesson=lesson, parent__isnull=True).prefetch_related('subtopics')
        return Response(TopicSerializer(updated, many=True).data)


# ── Subtopics ──

class SubtopicCreateAPIView(APIView):
    """POST lessons/<lesson_id>/subtopics/ — create a subtopic."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SubtopicCreateSerializer(
            data=request.data,
            context={'request': request, 'lesson': lesson},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        parent = data['parent']

        max_order = Topic.objects.filter(
            lesson=lesson, parent=parent
        ).aggregate(max_order=django_models.Max('order'))['max_order'] or 0

        subtopic = Topic.objects.create(
            lesson=lesson,
            parent=parent,
            title=data['title'],
            order=max_order + 1,
            weight=0,
        )

        distribute_subtopic_weights(lesson)
        subtopic.refresh_from_db()

        from .serializers import SubtopicSerializer
        return Response(
            SubtopicSerializer(subtopic).data,
            status=status.HTTP_201_CREATED,
        )


class SubtopicUpdateAPIView(APIView):
    """PATCH subtopics/<id>/ — update a subtopic."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def patch(self, request, pk):
        subtopic = get_object_or_404(Topic, pk=pk)
        if subtopic.parent is None:
            return Response(
                {'detail': NOT_A_SUBTOPIC},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lesson = subtopic.lesson
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SubtopicUpdateSerializer(subtopic, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        subtopic.refresh_from_db()

        from .serializers import SubtopicSerializer
        return Response(SubtopicSerializer(subtopic).data)


class SubtopicDistributeWeightsAPIView(APIView):
    """POST lessons/<lesson_id>/subtopics/distribute-weights/ — redistribute subtopic weights."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        distribute_subtopic_weights(lesson)

        from .serializers import TopicSerializer
        parent_topics = Topic.objects.filter(
            lesson=lesson, parent__isnull=True
        ).prefetch_related('subtopics')
        return Response(TopicSerializer(parent_topics, many=True).data)


# ── Grading ──

class GradingAPIView(APIView):
    """
    GET    lessons/<lesson_id>/grading/                      — grading page data
    POST   lessons/<lesson_id>/grading/                      — submit grades for a student
    PATCH  lessons/<lesson_id>/grading/                      — update grades for a student
    """
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def get(self, request, lesson_id):
        lesson = get_object_or_404(
            Lesson.objects.select_related(
                'offering', 'offering__subject',
                'offering__class_group', 'offering__academic_year',
            ),
            pk=lesson_id,
        )
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = GradingDataSerializer(lesson, context={'request': request})
        return Response(serializer.data)

    def post(self, request, lesson_id):
        return self._handle_grade_submit(request, lesson_id)

    def patch(self, request, lesson_id):
        return self._handle_grade_submit(request, lesson_id)

    def _handle_grade_submit(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)

        serializer = GradeSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student = get_object_or_404(Student, user__id=data['student_id'])

        if not can_grade_student(request.user, lesson, student):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        submit_grades(
            lesson=lesson,
            student=student,
            topics_data=data.get('topics', {}),
            subtopics_data=data.get('subtopics', {}),
            comment_mode=data.get('comment_mode', 'none'),
        )

        return Response(
            {'detail': 'Grades saved successfully.'},
            status=status.HTTP_200_OK,
        )


class GradingDeleteAPIView(APIView):
    """DELETE lessons/<lesson_id>/grading/<student_user_id>/ — delete all grades for a student."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def delete(self, request, lesson_id, student_user_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        student = get_object_or_404(Student, user__id=student_user_id)

        if not can_grade_student(request.user, lesson, student):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY},
                status=status.HTTP_403_FORBIDDEN,
            )

        delete_student_grades(lesson, student, user=request.user)

        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Calendar ──

class CalendarLessonListAPIView(APIView):
    """
    GET /api/v1/calendar/lessons/

    Returns lessons for a date range, auto-filtered by the requesting user's role:
    - Teacher: lessons from their teaching assignments
    - Student: lessons from their enrolled class
    - Parent: lessons from their children's classes (optionally filtered by child)
    - Admin/Supervisor/Principal: all lessons (with optional filters)

    Query params:
        start_date  (required) — YYYY-MM-DD
        end_date    (required) — YYYY-MM-DD
        class_group (optional) — class group ID (admin/supervisor/principal)
        subject     (optional) — subject ID
        quarter     (optional) — 1-4
        student     (optional) — student profile ID (parent only, to filter by child)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import datetime, timedelta

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not start_date or not end_date:
            return Response(
                {'detail': 'start_date and end_date are required (YYYY-MM-DD).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'detail': 'Invalid date format. Use YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (end_dt - start_dt).days > 30:
            return Response(
                {'detail': 'Date range cannot exceed 30 days.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lessons = Lesson.objects.select_related(
            'offering', 'offering__subject',
            'offering__class_group', 'offering__class_group__grade_level',
            'offering__academic_year',
        ).filter(date__gte=start_date, date__lte=end_date)

        user = request.user

        if is_admin_role(user):
            lessons = self._apply_admin_filters(lessons, request.query_params)
        elif is_teacher_role(user):
            lessons = self._filter_for_teacher(lessons, user)
        elif user.is_parent():
            lessons = self._filter_for_parent(lessons, user, request.query_params)
        elif user.is_student():
            lessons = self._filter_for_student(lessons, user)
        else:
            return Response([], status=status.HTTP_200_OK)

        subject_id = request.query_params.get('subject')
        if subject_id:
            lessons = lessons.filter(offering__subject_id=subject_id)

        quarter = request.query_params.get('quarter')
        if quarter:
            lessons = lessons.filter(quarter=quarter)

        lessons = lessons.order_by('date', 'order')
        lesson_list = list(lessons)

        teacher_cache = self._build_teacher_cache(lesson_list)

        serializer = CalendarLessonSerializer(
            lesson_list, many=True,
            context={'request': request, 'teacher_cache': teacher_cache},
        )
        return Response(serializer.data)

    def _apply_admin_filters(self, lessons, params):
        class_group_id = params.get('class_group')
        if class_group_id:
            lessons = lessons.filter(offering__class_group_id=class_group_id)
        return lessons

    def _filter_for_teacher(self, lessons, user):
        try:
            teacher = Teacher.objects.get(user=user)
            offering_ids = TeachingAssignment.objects.filter(
                teacher=teacher
            ).values_list('offering_id', flat=True)
            return lessons.filter(offering_id__in=offering_ids)
        except Teacher.DoesNotExist:
            return lessons.none()

    def _filter_for_parent(self, lessons, user, params):
        try:
            parent = Parent.objects.get(user=user)
            children = parent.students.all()

            student_id = params.get('student')
            if student_id:
                children = children.filter(pk=student_id)

            class_group_ids = Enrollment.objects.filter(
                student__in=children, status='active',
            ).values_list('class_group_id', flat=True)
            return lessons.filter(offering__class_group_id__in=class_group_ids)
        except Parent.DoesNotExist:
            return lessons.none()

    def _filter_for_student(self, lessons, user):
        try:
            student = Student.objects.get(user=user)
            class_group_ids = Enrollment.objects.filter(
                student=student, status='active',
            ).values_list('class_group_id', flat=True)
            return lessons.filter(offering__class_group_id__in=class_group_ids)
        except Student.DoesNotExist:
            return lessons.none()

    def _build_teacher_cache(self, lessons):
        offering_ids = list({l.offering_id for l in lessons if l.offering_id})
        if not offering_ids:
            return {}
        primary_assignments = TeachingAssignment.objects.filter(
            offering_id__in=offering_ids, role='primary',
        ).select_related('teacher__user')
        return {ta.offering_id: ta.teacher for ta in primary_assignments}


class FreezeQuarterAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not is_admin_role(request.user):
            return Response(
                {'detail': 'Only admins and supervisors can freeze quarters.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        quarter = request.data.get('quarter')
        if not quarter or int(quarter) not in (1, 2, 3, 4):
            return Response(
                {'detail': 'quarter is required (1-4).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            count = freeze_quarter_grades(pk, int(quarter), request.user)
        except SubjectOffering.DoesNotExist:
            return Response(
                {'detail': 'Offering not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response({
            'frozen_count': count,
            'quarter': int(quarter),
            'offering_id': pk,
        }, status=status.HTTP_201_CREATED)


class StudentGradeHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from core.permissions import can_access_student

        try:
            student = Student.objects.get(user_id=pk)
        except Student.DoesNotExist:
            return Response(
                {'detail': 'Student not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not can_access_student(request.user, student):
            return Response(
                {'detail': 'You do not have access to this student.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        year_id = request.query_params.get('year')
        snapshots = QuarterGradeSnapshot.objects.filter(
            student=student,
        ).select_related('offering__subject', 'academic_year').order_by(
            '-academic_year__year', 'offering__subject__name', 'quarter',
        )
        if year_id:
            snapshots = snapshots.filter(academic_year_id=year_id)

        data = []
        for s in snapshots:
            data.append({
                'id': s.id,
                'subject_name': s.offering.subject.name,
                'class_group': str(s.offering.class_group) if s.offering.class_group_id else None,
                'quarter': s.quarter,
                'academic_year': str(s.academic_year),
                'final_grade': float(s.final_grade),
                'percentage': float(s.percentage),
                'letter_grade': s.letter_grade,
                'lesson_count': s.lesson_count,
                'graded_lesson_count': s.graded_lesson_count,
                'frozen_at': s.frozen_at.isoformat(),
            })

        return Response(data)


class GradeAuditLogAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_admin_role(request.user):
            return Response(
                {'detail': 'Only admins can view audit logs.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        student_id = request.query_params.get('student')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        qs = TopicGrade.history.select_related(
            'topic', 'student__user',
        ).order_by('-history_date')

        if student_id:
            qs = qs.filter(student_id=student_id)
        if date_from:
            qs = qs.filter(history_date__date__gte=date_from)
        if date_to:
            qs = qs.filter(history_date__date__lte=date_to)

        qs = qs[:100]

        data = []
        for record in qs:
            data.append({
                'id': record.history_id,
                'action': record.get_history_type_display(),
                'date': record.history_date.isoformat(),
                'user': str(record.history_user) if record.history_user else None,
                'topic_id': record.topic_id,
                'student_id': record.student_id,
                'grade': record.grade,
                'comment': record.comment,
            })

        return Response(data)
