from django.db import models as django_models
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Student, Teacher
from apps.home.models import SubjectOffering, Enrollment, TeachingAssignment
from apps.lesson.models import Lesson, Topic, TopicGrade, MergedLessonComment
from core.permissions import (
    can_access_lesson, can_modify_lesson, can_grade_student,
    is_admin_role, is_teacher_role,
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
)


# ── Helpers ──

def _get_available_offerings(user):
    """Return the SubjectOffering queryset available to the requesting user."""
    if is_admin_role(user):
        return SubjectOffering.objects.select_related(
            'subject', 'class_group', 'academic_year'
        )
    if is_teacher_role(user):
        try:
            teacher = Teacher.objects.get(user=user)
            offering_ids = TeachingAssignment.objects.filter(
                teacher=teacher
            ).values_list('offering_id', flat=True)
            return SubjectOffering.objects.filter(
                id__in=offering_ids
            ).select_related('subject', 'class_group', 'academic_year')
        except Teacher.DoesNotExist:
            return SubjectOffering.objects.none()
    return SubjectOffering.objects.none()


def _build_graded_percent_map(lessons):
    """
    Build {lesson_id: percent} for a list of lessons in bulk — avoids N+1 queries.
    """
    from django.db.models import Count

    lesson_ids = [l.id for l in lessons]

    # Total enrolled students per offering
    offering_ids = list({l.offering_id for l in lessons if l.offering_id})
    total_by_offering = dict(
        Enrollment.objects.filter(
            class_group__offerings__id__in=offering_ids,
            status='active',
        ).values('class_group__offerings__id').annotate(
            cnt=Count('student', distinct=True)
        ).values_list('class_group__offerings__id', 'cnt')
    )

    # Students who have any TopicGrade per lesson
    graded_by_lesson = dict(
        Student.objects.filter(
            topicgrade__topic__lesson_id__in=lesson_ids
        ).values('topicgrade__topic__lesson_id').annotate(
            cnt=Count('id', distinct=True)
        ).values_list('topicgrade__topic__lesson_id', 'cnt')
    )

    result = {}
    for lesson in lessons:
        total = total_by_offering.get(lesson.offering_id, 0)
        graded = graded_by_lesson.get(lesson.id, 0)
        result[lesson.id] = int((graded / total) * 100) if total else 0
    return result


def _recalculate_topic_weights(lesson):
    """Set all parent topics to equal weight summing to 100."""
    topics = list(Topic.objects.filter(lesson=lesson, parent__isnull=True))
    count = len(topics)
    if not count:
        return
    equal_share = round(100 / count, 2)
    for t in topics:
        t.weight = equal_share
        t.save(update_fields=['weight'])


def _subtopic_weight_distribution(lesson):
    """Distribute subtopic weights equally under each parent topic."""
    parent_topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)
    for topic in parent_topics:
        subtopics = list(Topic.objects.filter(parent=topic, lesson=lesson))
        if not subtopics:
            continue
        count = len(subtopics)
        equal_share = round(100 / count, 2)
        if count > 1:
            remainder = round(100 - equal_share * (count - 1), 2)
            for s in subtopics[:-1]:
                s.weight = equal_share
                s.save(update_fields=['weight'])
            subtopics[-1].weight = remainder
            subtopics[-1].save(update_fields=['weight'])
        else:
            subtopics[0].weight = 100.0
            subtopics[0].save(update_fields=['weight'])


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
        ).all()

        if class_group_id and class_group_id != 'all':
            lessons = lessons.filter(offering__class_group_id=class_group_id)
        if subject_name and subject_name != 'all':
            lessons = lessons.filter(offering__subject__name=subject_name)
        if quarter and quarter != 'all':
            lessons = lessons.filter(quarter=quarter)

        lessons = list(lessons)
        graded_percent_map = _build_graded_percent_map(lessons)

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
        available = _get_available_offerings(request.user)
        if not available.filter(id=offering.id).exists():
            return Response(
                {'detail': 'You can only create lessons for your own offerings.'},
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
                {'detail': 'You do not have permission to view this lesson.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = LessonDetailSerializer(lesson, context={'request': request})
        return Response(serializer.data)

    def delete(self, request, pk):
        lesson = get_object_or_404(Lesson, pk=pk)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': 'You can only delete lessons for your own offerings.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        lesson.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Topics ──

class TopicCreateAPIView(APIView):
    """POST lessons/<lesson_id>/topics/ — create a parent topic."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': 'You can only create topics for your own lessons.'},
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

        _recalculate_topic_weights(lesson)
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
                {'detail': 'You can only update topics for your own lessons.'},
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
                {'detail': 'You can only delete topics for your own lessons.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        lesson_id = lesson.id
        topic.delete()

        lesson = get_object_or_404(Lesson, pk=lesson_id)
        _recalculate_topic_weights(lesson)
        _subtopic_weight_distribution(lesson)

        return Response(status=status.HTTP_204_NO_CONTENT)


class TopicDistributeWeightsAPIView(APIView):
    """POST lessons/<lesson_id>/topics/distribute-weights/ — equal weight distribution."""
    permission_classes = [IsAuthenticated, IsTeacherAdminOrSupervisor]

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': 'You can only modify topics for your own lessons.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)
        if not topics.exists():
            return Response(
                {'detail': 'No topics found for this lesson.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _recalculate_topic_weights(lesson)

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
                {'detail': 'You can only create subtopics for your own lessons.'},
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

        _subtopic_weight_distribution(lesson)
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
                {'detail': 'This topic is not a subtopic.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lesson = subtopic.lesson
        if not can_modify_lesson(request.user, lesson):
            return Response(
                {'detail': 'You can only update subtopics for your own lessons.'},
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
                {'detail': 'You can only modify subtopics for your own lessons.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        _subtopic_weight_distribution(lesson)

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
                {'detail': 'You can only view the grading page for your own lessons.'},
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
                {'detail': 'You can only grade students in your own subjects.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        comment_mode = data.get('comment_mode', 'none')
        topics_data = data.get('topics', {})
        subtopics_data = data.get('subtopics', {})
        to_merge = ''

        for topic in lesson.topics.filter(parent__isnull=True):
            topic_entry = topics_data.get(str(topic.id), {})
            subtopics = list(topic.subtopics.all())

            top_comment = topic_entry.get('comment', '').strip()
            top_comment_selected = topic_entry.get('comment_selected', False)

            if comment_mode == 'merged':
                to_merge += top_comment + ' \n\n'

            # Grade each subtopic
            for sub in subtopics:
                sub_entry = subtopics_data.get(str(sub.id), {})
                covered = sub_entry.get('covered', False)
                sub_comment = sub_entry.get('comment', '').strip()
                sub_comment_selected = sub_entry.get('comment_selected', False)

                if comment_mode == 'merged':
                    to_merge += sub_comment + '\n\n'

                TopicGrade.objects.update_or_create(
                    student=student,
                    topic=sub,
                    defaults={
                        'grade': 100 if covered else 0,
                        'comment': sub_comment,
                        'comment_selected': sub_comment_selected,
                    },
                )

            # Grade the parent topic
            if subtopics:
                topic_grade_value = topic.calculate_subtopics_grade(student)
            else:
                covered = topic_entry.get('covered', False)
                topic_grade_value = 100 if covered else 0

            TopicGrade.objects.update_or_create(
                student=student,
                topic=topic,
                defaults={
                    'grade': topic_grade_value,
                    'comment': top_comment,
                    'comment_selected': top_comment_selected,
                },
            )

        # Handle comment mode
        if comment_mode == 'merged':
            # Clear per-topic selected flags, write merged comment
            TopicGrade.objects.filter(
                topic__lesson=lesson,
                student=student,
            ).update(comment_selected=False)

            MergedLessonComment.objects.update_or_create(
                lesson=lesson,
                student=student,
                defaults={'comment_text': to_merge},
            )
        else:
            # Remove any previous merged comment when mode is selected/none
            MergedLessonComment.objects.filter(
                lesson=lesson,
                student=student,
            ).delete()

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
                {'detail': 'You can only delete grades for students in your own subjects.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        TopicGrade.objects.filter(student=student, topic__lesson=lesson).delete()
        MergedLessonComment.objects.filter(lesson=lesson, student=student).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
