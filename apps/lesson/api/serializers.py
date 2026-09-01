from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.achievement.models import Attachment
from apps.lesson.models import (
    Lesson, Topic, TopicGrade, MergedLessonComment,
    SubjectSchedule, ScheduleSession, ScheduleAttendance,
    Homework, HomeworkGrade,
)
from apps.lesson.services import (
    MAX_HOMEWORK_ATTACHMENTS,
    attach_files_to_homeworks,
    delete_homework_attachments,
    validate_homework_attachments,
)
from apps.home.models import SubjectOffering, Enrollment, TeachingAssignment
from apps.authentication.models import Student


# ── Calendar serializer ──

class CalendarLessonSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='offering.subject.name', read_only=True)
    subject_id = serializers.IntegerField(source='offering.subject_id', read_only=True)
    class_group_name = serializers.CharField(source='offering.class_group.__str__', read_only=True)
    class_group_id = serializers.IntegerField(source='offering.class_group_id', read_only=True)
    teacher = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            'id', 'title', 'date', 'status', 'quarter', 'unit', 'order',
            'subject_name', 'subject_id', 'class_group_name', 'class_group_id',
            'teacher',
        ]

    def get_teacher(self, obj):
        cache = self.context.get('teacher_cache')
        if cache is not None:
            t = cache.get(obj.offering_id)
            if t:
                return {'id': t.user_id, 'full_name': t.user.get_full_name()}
        return None


# ── Shared nested serializers ──

class SubtopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = ['id', 'title', 'order', 'weight', 'comment_template']


class TopicSerializer(serializers.ModelSerializer):
    subtopics = SubtopicSerializer(many=True, read_only=True)

    class Meta:
        model = Topic
        fields = ['id', 'title', 'order', 'weight', 'comment_template', 'subtopics']


class OfferingMinimalSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    class_group_name = serializers.CharField(source='class_group.__str__', read_only=True)
    academic_year_label = serializers.CharField(source='academic_year.year', read_only=True)

    class Meta:
        model = SubjectOffering
        fields = ['id', 'subject_name', 'class_group_name', 'academic_year_label']


# ── Lesson serializers ──

class LessonListSerializer(serializers.ModelSerializer):
    offering = OfferingMinimalSerializer(read_only=True)
    graded_percent = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            'id', 'title', 'description', 'date', 'order', 'status',
            'quarter', 'unit', 'offering', 'graded_percent',
            'created_at', 'updated_at',
        ]

    def get_graded_percent(self, obj) -> int:
        """
        Percent of enrolled students who have at least one TopicGrade for this lesson.
        Pre-computed data is injected via serializer context['graded_percent_map'] when
        available (bulk path) to avoid N+1 queries.
        """
        graded_map = self.context.get('graded_percent_map')
        if graded_map is not None:
            return graded_map.get(obj.id, 0)

        # Fallback: per-object calculation (used in detail / non-list contexts)
        if not obj.offering:
            return 0
        total = Enrollment.objects.filter(
            class_group=obj.offering.class_group,
            status='active',
        ).count()
        if not total:
            return 0
        graded = (
            Student.objects
            .filter(topicgrade__topic__lesson=obj)
            .distinct()
            .count()
        )
        return int((graded / total) * 100)


class LessonDetailSerializer(serializers.ModelSerializer):
    offering = OfferingMinimalSerializer(read_only=True)
    topics = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    student_grades = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            'id', 'title', 'description', 'date', 'order', 'status',
            'quarter', 'unit', 'offering', 'topics', 'students',
            'student_grades', 'created_at', 'updated_at',
        ]

    def get_topics(self, obj):
        parent_topics = Topic.objects.filter(
            lesson=obj, parent__isnull=True
        ).prefetch_related('subtopics').order_by('order', 'id')
        return TopicSerializer(parent_topics, many=True).data

    def get_students(self, obj):
        if not obj.offering:
            return []
        students = Student.objects.filter(
            enrollments__class_group=obj.offering.class_group,
            enrollments__academic_year=obj.offering.academic_year,
            enrollments__status='active',
        ).select_related('user').distinct()
        return [
            {
                'id': s.id,
                'user_id': s.user.id,
                'full_name': s.user.get_full_name(),
                'username': s.user.username,
            }
            for s in students
        ]

    def get_student_grades(self, obj):
        if not obj.offering:
            return {}

        students = list(Student.objects.filter(
            enrollments__class_group=obj.offering.class_group,
            enrollments__academic_year=obj.offering.academic_year,
            enrollments__status='active',
        ).distinct())

        all_topic_grades = TopicGrade.objects.filter(
            topic__lesson=obj,
            student__in=students,
        ).values('student_id', 'topic_id', 'grade', 'comment', 'comment_selected')

        grades_map = {}
        topic_grades_by_student = {}
        for tg in all_topic_grades:
            grades_map[(tg['topic_id'], tg['student_id'])] = tg['grade']
            student_map = topic_grades_by_student.setdefault(tg['student_id'], {})
            student_map[tg['topic_id']] = {
                'grade': tg['grade'],
                'comment': tg['comment'] or '',
                'comment_selected': tg['comment_selected'],
            }

        # Subtopic ids per parent topic for comment aggregation
        parent_topics = Topic.objects.filter(
            lesson=obj, parent__isnull=True
        ).prefetch_related('subtopics')
        topic_subtopic_ids = {
            t.id: [s.id for s in t.subtopics.all()] for t in parent_topics
        }

        result = {}
        for student in students:
            key = str(student.user.id)
            result[key] = {
                'grade_total': round(obj.calculate_student_grade(student, grades_map), 1),
            }
            per_topic = topic_grades_by_student.get(student.id, {})
            result[key].update({str(k): v for k, v in per_topic.items()})

            # Resolve comment display for parent topics that have subtopics
            for topic_id, subtopic_ids in topic_subtopic_ids.items():
                entry = result[key].get(str(topic_id))
                if not isinstance(entry, dict) or not subtopic_ids:
                    continue
                selected_sub_comment = None
                for sub_id in subtopic_ids:
                    sub_entry = per_topic.get(sub_id, {})
                    if sub_entry.get('comment_selected') and sub_entry.get('comment'):
                        selected_sub_comment = sub_entry['comment']
                        break
                if selected_sub_comment:
                    entry['comment'] = selected_sub_comment
                    entry['comment_selected'] = True
                elif not entry.get('comment'):
                    sub_comments = [
                        per_topic[sub_id]['comment']
                        for sub_id in subtopic_ids
                        if per_topic.get(sub_id, {}).get('comment')
                    ]
                    if sub_comments:
                        entry['comment'] = ' | '.join(sub_comments)

        return result


class LessonCreateSerializer(serializers.ModelSerializer):
    offering = serializers.PrimaryKeyRelatedField(
        queryset=SubjectOffering.objects.select_related('subject', 'class_group', 'academic_year')
    )

    class Meta:
        model = Lesson
        fields = ['offering', 'title', 'description', 'date', 'order', 'status', 'quarter', 'unit']

    def validate_quarter(self, value):
        if not (1 <= value <= 4):
            raise serializers.ValidationError('Quarter must be between 1 and 4.')
        return value

    def validate_unit(self, value):
        if not (1 <= value <= 15):
            raise serializers.ValidationError('Unit must be between 1 and 15.')
        return value


# ── Topic serializers ──

class TopicCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    comment_template = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=''
    )


class TopicUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = ['title', 'weight', 'comment_template']
        extra_kwargs = {
            'title': {'required': False},
            'weight': {'required': False},
            'comment_template': {'required': False, 'allow_blank': True},
        }


# ── Subtopic serializers ──

class SubtopicCreateSerializer(serializers.Serializer):
    parent = serializers.PrimaryKeyRelatedField(queryset=Topic.objects.all())
    title = serializers.CharField(max_length=255)

    def validate_parent(self, parent):
        # parent must belong to the lesson resolved in the view
        lesson = self.context.get('lesson')
        if lesson and parent.lesson_id != lesson.id:
            raise serializers.ValidationError(
                'Parent topic does not belong to this lesson.'
            )
        if parent.parent is not None:
            raise serializers.ValidationError(
                'Cannot nest a subtopic under another subtopic.'
            )
        return parent


class SubtopicUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = ['title', 'weight', 'comment_template']
        extra_kwargs = {
            'title': {'required': False},
            'weight': {'required': False},
            'comment_template': {'required': False, 'allow_blank': True},
        }


# ── Grading serializers ──

class TopicGradeEntrySerializer(serializers.Serializer):
    """A single topic/subtopic grade entry inside the grade submit payload."""
    covered = serializers.BooleanField(required=False, default=False)
    comment = serializers.CharField(required=False, allow_blank=True, default='')
    comment_selected = serializers.BooleanField(required=False, default=False)


class GradeSubmitSerializer(serializers.Serializer):
    """
    Write serializer for POST/PATCH lessons/<id>/grading/.

    topics: dict keyed by topic_id (str or int) with TopicGradeEntrySerializer data.
    subtopics: dict keyed by subtopic_id (str or int) with TopicGradeEntrySerializer data.
    """
    student_id = serializers.IntegerField(
        help_text='user.id of the student to grade'
    )
    comment_mode = serializers.ChoiceField(
        choices=['merged', 'selected', 'none'],
        required=False,
        default='none',
    )
    topics = serializers.DictField(
        child=TopicGradeEntrySerializer(),
        required=False,
        default=dict,
    )
    subtopics = serializers.DictField(
        child=TopicGradeEntrySerializer(),
        required=False,
        default=dict,
    )


class GradingStudentSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = Student
        fields = ['id', 'user_id', 'full_name']


class GradingDataSerializer(serializers.ModelSerializer):
    """Read serializer for the grading page endpoint."""
    topics = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    topic_grade_map = serializers.SerializerMethodField()
    student_grades = serializers.SerializerMethodField()
    merged_comment_map = serializers.SerializerMethodField()
    selected_comments_map = serializers.SerializerMethodField()
    comment_templates = serializers.SerializerMethodField()
    comment_modes = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            'id', 'title', 'quarter', 'unit', 'status',
            'topics', 'students', 'topic_grade_map',
            'student_grades', 'merged_comment_map',
            'selected_comments_map', 'comment_templates', 'comment_modes',
        ]

    def _get_students(self, obj):
        if hasattr(self, '_students_cache'):
            return self._students_cache
        if not obj.offering:
            self._students_cache = []
            return self._students_cache
        self._students_cache = list(Student.objects.filter(
            enrollments__class_group=obj.offering.class_group,
            enrollments__academic_year=obj.offering.academic_year,
            enrollments__status='active',
        ).select_related('user').distinct())
        return self._students_cache

    def _get_grade_data(self, obj):
        if hasattr(self, '_grade_data_cache'):
            return self._grade_data_cache

        students = self._get_students(obj)
        rows = (
            TopicGrade.objects
            .filter(topic__lesson=obj, student__in=students)
            .select_related('student__user')
            .values(
                'student__user_id', 'student_id',
                'topic_id', 'grade', 'comment', 'comment_selected',
            )
        )

        topic_grade_map = {}
        grades_map = {}
        for g in rows:
            uid = g['student__user_id']
            key = f"{uid}-{g['topic_id']}"
            topic_grade_map[key] = {
                'grade': round(g['grade'], 1),
                'comment': g['comment'] or '',
                'comment_selected': g['comment_selected'],
            }
            grades_map[(g['topic_id'], g['student_id'])] = g['grade']

        merged_comments = (
            MergedLessonComment.objects
            .filter(lesson=obj, student__in=students)
            .select_related('student__user')
            .values('student__user_id', 'comment_text', 'is_merged')
        )
        merged_comment_map = {
            mc['student__user_id']: mc['comment_text'] for mc in merged_comments if mc['is_merged']
        }

        selected_qs = (
            TopicGrade.objects
            .filter(topic__lesson=obj, comment_selected=True)
            .select_related('student__user', 'topic')
            .values('student__user_id', 'topic__title', 'comment')
            .exclude(comment__isnull=True).exclude(comment='')
        )
        selected_comments_map = {}
        for sc in selected_qs:
            uid = sc['student__user_id']
            if uid in selected_comments_map:
                selected_comments_map[uid] += '\n\n' + sc['comment']
            else:
                selected_comments_map[uid] = sc['comment']

        student_grades = {}
        for student in students:
            student_grades[student.user.id] = round(
                obj.calculate_student_grade(student, grades_map), 1
            )

        self._grade_data_cache = {
            'topic_grade_map': topic_grade_map,
            'grades_map': grades_map,
            'merged_comment_map': merged_comment_map,
            'selected_comments_map': selected_comments_map,
            'student_grades': student_grades,
        }
        return self._grade_data_cache

    def get_topics(self, obj):
        all_topics = Topic.objects.filter(lesson=obj).order_by('order', 'id')
        return TopicSerializer(
            [t for t in all_topics if t.parent_id is None],
            many=True,
        ).data

    def get_students(self, obj):
        return GradingStudentSerializer(self._get_students(obj), many=True).data

    def get_topic_grade_map(self, obj):
        return self._get_grade_data(obj)['topic_grade_map']

    def get_student_grades(self, obj):
        return {
            str(k): v
            for k, v in self._get_grade_data(obj)['student_grades'].items()
        }

    def get_merged_comment_map(self, obj):
        return {
            str(k): v
            for k, v in self._get_grade_data(obj)['merged_comment_map'].items()
        }

    def get_selected_comments_map(self, obj):
        return {
            str(k): v
            for k, v in self._get_grade_data(obj)['selected_comments_map'].items()
        }

    def get_comment_templates(self, obj):
        topics = Topic.objects.filter(lesson=obj)
        return {str(t.id): t.comment_template for t in topics}

    def get_comment_modes(self, obj):
        data = self._get_grade_data(obj)
        merged = data['merged_comment_map']
        selected = data['selected_comments_map']
        modes = {}
        for student in self._get_students(obj):
            uid = student.user.id
            if uid in selected:
                modes[str(uid)] = 'selected'
            elif uid in merged:
                modes[str(uid)] = 'merged'
            else:
                modes[str(uid)] = None
        return modes


# ── Schedule session serializers ──

class ScheduleSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleSession
        fields = ['id', 'schedule', 'weekday', 'time_start', 'time_end']
        read_only_fields = ['schedule']


class ScheduleSessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleSession
        fields = ['weekday', 'time_start', 'time_end']

    def validate_weekday(self, value):
        if not (0 <= value <= 6):
            raise serializers.ValidationError(
                'Weekday must be between 0 (Monday) and 6 (Sunday).'
            )
        return value

    def validate(self, attrs):
        """
        A slot must end after it starts, and must not overlap another slot of
        the same schedule on the same weekday.

        Overlap is the time-based replacement for the old weekday/order
        uniqueness: two lessons of the same subject cannot run at once, and
        touching slots (10:00–10:45 then 10:45–11:30) are not an overlap.
        """
        schedule = self.context['schedule']
        weekday = attrs.get('weekday', getattr(self.instance, 'weekday', None))
        time_start = attrs.get('time_start', getattr(self.instance, 'time_start', None))
        time_end = attrs.get('time_end', getattr(self.instance, 'time_end', None))

        if time_start is not None and time_end is not None and time_end <= time_start:
            raise serializers.ValidationError(
                {'time_end': 'time_end must be later than time_start.'}
            )

        clash = ScheduleSession.objects.filter(
            schedule=schedule,
            weekday=weekday,
            time_start__lt=time_end,
            time_end__gt=time_start,
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                'This schedule already has a session overlapping that time on '
                'that weekday.'
            )
        return attrs


# ── Subject schedule serializers ──

def schedule_title(schedule):
    """
    What to call a schedule row: its subject, or its description.

    A schedule without an offering is a free timetable entry (a break, an
    assembly, a club) and carries its own description instead of a subject.
    """
    if schedule.offering_id:
        return schedule.offering.subject.name
    return schedule.description or ''


class OtherScheduleSessionSerializer(serializers.ModelSerializer):
    """A slot in the class group's timetable owned by a different entry."""
    offering_id = serializers.IntegerField(source='schedule.offering_id', read_only=True)
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleSession
        fields = [
            'id', 'schedule', 'offering_id', 'subject_name',
            'weekday', 'time_start', 'time_end',
        ]

    def get_subject_name(self, obj):
        """The subject's name, or the description for an offering-less entry."""
        return schedule_title(obj.schedule)


class SubjectScheduleSerializer(serializers.ModelSerializer):
    offering = OfferingMinimalSerializer(read_only=True, allow_null=True)
    offering_id = serializers.IntegerField(read_only=True, allow_null=True)
    type = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    sessions = serializers.SerializerMethodField()
    other_sessions = serializers.SerializerMethodField()

    class Meta:
        model = SubjectSchedule
        fields = [
            'id', 'type', 'title', 'offering', 'offering_id', 'description',
            'quarter', 'sessions', 'other_sessions',
        ]

    def get_type(self, obj):
        """'subject' for an offering's timetable, 'other' for a free entry."""
        return (
            SubjectSchedule.SUBJECT_CHOICE if obj.offering_id
            else SubjectSchedule.OTHER_CHOICE
        )

    def get_title(self, obj):
        return schedule_title(obj)

    def get_sessions(self, obj):
        sessions = sorted(
            obj.sessions.all(),
            key=lambda s: (s.weekday, s.time_start, s.time_end),
        )
        return ScheduleSessionSerializer(sessions, many=True).data

    def get_other_sessions(self, obj):
        """
        The rest of the class group's timetable for this quarter — sessions of
        every *other* subject, for read-only display alongside `sessions`.

        Pre-computed data is injected via context['other_sessions_map'] on the
        bulk (list) path; otherwise it is resolved per object.
        """
        sessions_map = self.context.get('other_sessions_map')
        if sessions_map is None:
            from apps.lesson.services import build_other_sessions_map
            sessions_map = build_other_sessions_map([obj])

        return OtherScheduleSessionSerializer(
            sessions_map.get(obj.id, []), many=True,
        ).data


class TeachingAssignmentListSerializer(serializers.ModelSerializer):
    """
    One offering with its primary teacher.

    `id` is the SubjectOffering id, not the TeachingAssignment id — the list is
    keyed by offering, one row each.
    """
    id = serializers.IntegerField(source='offering_id', read_only=True)
    subject_name = serializers.CharField(source='offering.subject.name', read_only=True)
    class_group_name = serializers.CharField(
        source='offering.class_group.__str__', read_only=True,
    )
    teacher_name = serializers.CharField(source='teacher.__str__', read_only=True)
    academic_year = serializers.CharField(
        source='offering.academic_year.year', read_only=True,
    )
    academic_year_id = serializers.IntegerField(
        source='offering.academic_year_id', read_only=True,
    )

    class Meta:
        model = TeachingAssignment
        fields = [
            'id', 'subject_name', 'class_group_name',
            'teacher_name', 'academic_year', 'academic_year_id',
        ]


class SubjectScheduleWriteSerializer(serializers.ModelSerializer):
    offering = serializers.PrimaryKeyRelatedField(
        queryset=SubjectOffering.objects.select_related(
            'subject', 'class_group', 'academic_year'
        ),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = SubjectSchedule
        fields = ['offering', 'description', 'quarter']
        # The model's (offering, quarter) uniqueness is checked in validate()
        # instead: DRF's automatic UniqueTogetherValidator would make `offering`
        # mandatory on create, and an offering-less entry has none to give.
        validators = []

    def validate_quarter(self, value):
        if not (1 <= value <= 4):
            raise serializers.ValidationError('Quarter must be between 1 and 4.')
        return value

    def validate(self, attrs):
        """
        A schedule is either a subject's or a free entry, never neither.

        With no offering the row has nothing to name it, so `description`
        becomes mandatory, and one offering still gets a single schedule per
        quarter. On a PATCH the fields already stored count too — a request that
        only changes the quarter must not have to resend them.
        """
        offering = attrs.get('offering', getattr(self.instance, 'offering', None))
        description = attrs.get(
            'description', getattr(self.instance, 'description', None),
        )
        quarter = attrs.get('quarter', getattr(self.instance, 'quarter', None))

        if offering is None and not (description or '').strip():
            raise serializers.ValidationError(
                {'description': 'Required when the schedule has no offering.'}
            )

        if offering is not None:
            duplicate = SubjectSchedule.objects.filter(
                offering=offering, quarter=quarter,
            )
            if self.instance is not None:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError(
                    'This offering already has a schedule for that quarter.'
                )
        return attrs


# ── Attendance serializers ──

class ScheduleAttendanceSerializer(serializers.ModelSerializer):
    student_user_id = serializers.IntegerField(source='student.user_id', read_only=True)
    student_name = serializers.CharField(
        source='student.user.get_full_name', read_only=True
    )
    schedule_id = serializers.IntegerField(source='session.schedule_id', read_only=True)
    subject_name = serializers.CharField(
        source='session.schedule.offering.subject.name', read_only=True
    )

    class Meta:
        model = ScheduleAttendance
        fields = [
            'id', 'session', 'schedule_id', 'subject_name',
            'student', 'student_user_id', 'student_name',
            'date', 'status', 'created_at',
        ]
        read_only_fields = ['session', 'created_at']


class ScheduleAttendanceWriteSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.select_related('user')
    )

    class Meta:
        model = ScheduleAttendance
        fields = ['student', 'date', 'status']

    def validate_student(self, student):
        """The student must be actively enrolled in the offering's class group."""
        session = self.context['session']
        offering = session.schedule.offering
        if offering is None:
            raise serializers.ValidationError(
                'Attendance can only be recorded against a schedule bound to a '
                'subject offering.'
            )
        enrolled = Enrollment.objects.filter(
            student=student,
            class_group=offering.class_group,
            academic_year=offering.academic_year,
            status='active',
        ).exists()
        if not enrolled:
            raise serializers.ValidationError(
                'This student is not enrolled in the class group of this schedule.'
            )
        return student

    def validate(self, attrs):
        """One attendance row per student per session per date."""
        session = self.context['session']
        student = attrs.get('student', getattr(self.instance, 'student', None))
        date = attrs.get('date', getattr(self.instance, 'date', None))

        duplicate = ScheduleAttendance.objects.filter(
            session=session, student=student, date=date,
        )
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError(
                'Attendance for this student on this date is already recorded.'
            )
        return attrs


# ── Homework serializers ──

class HomeworkAttachmentSerializer(serializers.ModelSerializer):
    """One file hanging off a homework. `url` is absolute when a request is in
    context, so the frontend can link to it directly."""
    name = serializers.CharField(source='original_name', read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ['id', 'name', 'url', 'file_type', 'created_at']
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.URI)
    def get_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class HomeworkSerializer(serializers.ModelSerializer):
    offering = OfferingMinimalSerializer(read_only=True)
    class_group_id = serializers.IntegerField(source='offering.class_group_id', read_only=True)
    subject_id = serializers.IntegerField(source='offering.subject_id', read_only=True)
    teacher = serializers.SerializerMethodField()
    attachments = HomeworkAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Homework
        fields = [
            'id', 'description', 'offering', 'class_group_id', 'subject_id',
            'teaching_assignment', 'teacher', 'max_grade', 'due_date',
            'is_active', 'attachments', 'created_at',
        ]
        read_only_fields = fields

    def get_teacher(self, obj):
        teacher = obj.teaching_assignment.teacher
        return {'id': teacher.user_id, 'full_name': teacher.user.get_full_name()}


class StudentHomeworkSerializer(HomeworkSerializer):
    """
    Homework as seen from one student: same payload plus that student's own
    grade row, or null when there is no row at all / it is not visible to the
    caller.

    A row that exists may still carry `grade: null` — the teacher opened it to
    leave a comment, or marked the student as awaiting a mark — so clients must
    tell "no row" apart from "row with no mark".
    """
    student_grade = serializers.SerializerMethodField()

    class Meta(HomeworkSerializer.Meta):
        fields = HomeworkSerializer.Meta.fields + ['student_grade']
        read_only_fields = fields

    def get_student_grade(self, obj):
        grade = self.context.get('grade_map', {}).get(obj.pk)
        if grade is None:
            return None
        return {
            'id': grade.pk,
            'grade': grade.grade,
            'comments': grade.comments,
            'created_at': grade.created_at,
        }


class HomeworkCreateSerializer(serializers.Serializer):
    """
    One payload creates the same homework in several offerings at once.

    `offerings` is a list so a teacher can hand the same task to every class
    they teach in a single request; one Homework row is created per offering.
    """
    offerings = serializers.PrimaryKeyRelatedField(
        queryset=SubjectOffering.objects.select_related(
            'subject', 'class_group', 'academic_year',
        ),
        many=True,
        allow_empty=False,
        write_only=True,
    )
    description = serializers.CharField()
    max_grade = serializers.IntegerField(min_value=1, max_value=100)
    due_date = serializers.DateField()
    is_active = serializers.BooleanField(required=False, default=False)
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True,
        write_only=True,
        max_length=MAX_HOMEWORK_ATTACHMENTS,
        help_text=(
            'Files to attach, sent as multipart/form-data. Every offering in '
            '`offerings` gets its own copy of each file.'
        ),
    )

    def validate_offerings(self, offerings):
        """Drop repeats so the same offering is never created twice."""
        unique, seen = [], set()
        for offering in offerings:
            if offering.pk not in seen:
                seen.add(offering.pk)
                unique.append(offering)
        return unique

    def validate_attachments(self, files):
        validate_homework_attachments(files)
        return files


class HomeworkWriteSerializer(serializers.ModelSerializer):
    """
    Update payload. The offering stays fixed — moving a homework to another
    class means creating it there instead.

    Attachments are edited incrementally: `attachments` appends new files and
    `remove_attachments` drops existing ones by id. Neither is a replacement of
    the whole set, so a PUT that omits both leaves the files untouched.
    """
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True,
        write_only=True,
        max_length=MAX_HOMEWORK_ATTACHMENTS,
        help_text='New files to add, sent as multipart/form-data.',
    )
    remove_attachments = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        write_only=True,
        help_text='Ids of attachments to delete from this homework.',
    )

    class Meta:
        model = Homework
        fields = [
            'description', 'max_grade', 'due_date', 'is_active',
            'attachments', 'remove_attachments',
        ]

    def validate(self, attrs):
        """
        Check the batch against what the homework already holds, minus whatever
        this same request is about to remove.
        """
        files = attrs.get('attachments') or []
        if files and self.instance is not None:
            removing = len(set(attrs.get('remove_attachments') or []))
            existing = self.instance.attachments.count() - removing
            validate_homework_attachments(files, existing_count=max(existing, 0))
        return attrs

    def update(self, instance, validated_data):
        files = validated_data.pop('attachments', [])
        remove_ids = validated_data.pop('remove_attachments', [])
        request = self.context.get('request')

        # Removals run first so a request can swap files without tripping the
        # per-homework cap.
        delete_homework_attachments(instance, remove_ids)
        homework = super().update(instance, validated_data)
        attach_files_to_homeworks(
            [homework], files, request.user if request else None,
        )
        return homework


class HomeworkGradeSerializer(serializers.ModelSerializer):
    student_user_id = serializers.IntegerField(source='student.user_id', read_only=True)
    student_name = serializers.CharField(
        source='student.user.get_full_name', read_only=True
    )
    homework_max_grade = serializers.IntegerField(source='homework.max_grade', read_only=True)
    offering_id = serializers.IntegerField(source='homework.offering_id', read_only=True)
    subject_name = serializers.CharField(
        source='homework.offering.subject.name', read_only=True
    )
    due_date = serializers.DateField(source='homework.due_date', read_only=True)

    class Meta:
        model = HomeworkGrade
        fields = [
            'id', 'homework', 'offering_id', 'subject_name', 'due_date',
            'student', 'student_user_id', 'student_name',
            'grade', 'comments', 'homework_max_grade', 'created_at',
        ]
        read_only_fields = fields


class HomeworkGradeWriteSerializer(serializers.ModelSerializer):
    """
    Create / update payload for a single homework grade.

    Both `grade` and `comments` are optional and nullable: a row may carry a
    mark with no feedback, feedback with no mark yet, or neither — an empty
    placeholder for a student who has not handed anything in. Sending `null`
    clears a value that was set before.
    """
    student = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.select_related('user'),
        help_text='Student profile id of the student being graded.',
    )
    grade = serializers.IntegerField(
        min_value=0, required=False, allow_null=True,
        help_text='Points awarded, or null for "not graded yet".',
    )
    comments = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        help_text='Free-text feedback for the student.',
    )

    class Meta:
        model = HomeworkGrade
        fields = ['student', 'grade', 'comments']

    def validate_student(self, student):
        """The student must be actively enrolled in the homework's class group."""
        homework = self.context['homework']
        offering = homework.offering
        enrolled = Enrollment.objects.filter(
            student=student,
            class_group=offering.class_group,
            academic_year=offering.academic_year,
            status='active',
        ).exists()
        if not enrolled:
            raise serializers.ValidationError(
                'This student is not enrolled in the class group of this homework.'
            )
        return student

    def validate_grade(self, grade):
        """
        min_value on the field already rejects negatives; null means the work
        is simply not marked yet, so there is no ceiling to check against.
        """
        homework = self.context['homework']
        if grade is not None and grade > homework.max_grade:
            raise serializers.ValidationError(
                f'Grade cannot exceed the maximum of {homework.max_grade}.'
            )
        return grade

    def validate(self, attrs):
        """One grade per student per homework."""
        homework = self.context['homework']
        student = attrs.get('student', getattr(self.instance, 'student', None))

        duplicate = HomeworkGrade.objects.filter(homework=homework, student=student)
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError(
                'This student is already graded for this homework.'
            )
        return attrs


# ── Analytics response shapes ──
#
# Declared for the OpenAPI schema only. The analytics views assemble their
# payloads as plain dicts — the numbers come out of aggregation, not out of
# model instances, and running them back through a serializer would only
# re-copy them — so these are what drf-spectacular documents rather than what
# builds the response. Keep them in step with apps/lesson/api/analytics.py.


class GradingNoteSerializer(serializers.Serializer):
    missing_topics_as = serializers.CharField(
        help_text='Always "zero": an ungraded topic counts as 0.',
    )


class CoverageSerializer(serializers.Serializer):
    topic_count = serializers.IntegerField()
    graded_topic_count = serializers.IntegerField()


class AnalyticsStudentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    short_name = serializers.CharField()


class AnalyticsOfferingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    subject = serializers.CharField()
    subject_id = serializers.IntegerField()
    class_group = serializers.CharField(allow_null=True)
    academic_year = serializers.CharField(allow_null=True)
    max_points = serializers.IntegerField()
    grading_strategy = serializers.CharField()


class LessonFiltersSerializer(serializers.Serializer):
    quarter = serializers.IntegerField(allow_null=True)
    unit = serializers.IntegerField(allow_null=True)
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)


class TrajectoryPointSerializer(serializers.Serializer):
    lesson_id = serializers.IntegerField()
    title = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    order = serializers.IntegerField()
    quarter = serializers.IntegerField()
    unit = serializers.IntegerField()
    status = serializers.CharField()
    student_grade = serializers.FloatField()
    coverage = CoverageSerializer()
    # Present unless include_class_stats=false.
    class_mean = serializers.FloatField(required=False)
    class_median = serializers.FloatField(required=False)
    p25 = serializers.FloatField(required=False)
    p75 = serializers.FloatField(required=False)
    class_min = serializers.FloatField(required=False)
    class_max = serializers.FloatField(required=False)
    class_size = serializers.IntegerField(required=False)
    rank = serializers.IntegerField(required=False)


class TrajectorySummarySerializer(serializers.Serializer):
    lesson_count = serializers.IntegerField()
    student_mean = serializers.FloatField()
    class_mean = serializers.FloatField(allow_null=True)
    delta = serializers.FloatField(allow_null=True)
    trend_slope = serializers.FloatField(help_text='Least-squares points per lesson.')
    coverage = CoverageSerializer()


class StudentTrajectorySerializer(serializers.Serializer):
    student = AnalyticsStudentSerializer()
    offering = AnalyticsOfferingSerializer()
    filters = LessonFiltersSerializer()
    grading = GradingNoteSerializer()
    points = TrajectoryPointSerializer(many=True)
    summary = TrajectorySummarySerializer()


class HeatmapFiltersSerializer(LessonFiltersSerializer):
    group_by = serializers.CharField()
    include_subtopics = serializers.BooleanField()


class HeatmapColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    parent = serializers.CharField(allow_null=True)
    weight = serializers.FloatField(help_text='Mean weight of the topics folded in.')
    lesson_count = serializers.IntegerField()
    topic_count = serializers.IntegerField()


class HeatmapScaleSerializer(serializers.Serializer):
    min = serializers.IntegerField()
    max = serializers.IntegerField()


class TopicHeatmapSerializer(serializers.Serializer):
    offering = AnalyticsOfferingSerializer()
    filters = HeatmapFiltersSerializer()
    grading = GradingNoteSerializer()
    scale = HeatmapScaleSerializer()
    students = AnalyticsStudentSerializer(many=True)
    topics = HeatmapColumnSerializer(many=True)
    matrix = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField()),
        help_text='matrix[i][j] = students[i] on topics[j]. Dense, never null.',
    )
    coverage = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField()),
        help_text='Topic grades actually entered behind each cell.',
    )
    row_means = serializers.ListField(child=serializers.FloatField())
    column_means = serializers.ListField(child=serializers.FloatField())
    class_size = serializers.IntegerField()
    lesson_count = serializers.IntegerField()
    truncated = serializers.BooleanField(
        help_text='True when columns were capped; narrow with quarter or unit.',
    )


class RadarAxisSerializer(serializers.Serializer):
    offering_id = serializers.IntegerField()
    subject_id = serializers.IntegerField()
    subject = serializers.CharField()
    language_group = serializers.CharField()
    value = serializers.FloatField()
    source = serializers.ChoiceField(choices=['snapshot', 'live'])
    lesson_count = serializers.IntegerField()
    graded_lesson_count = serializers.IntegerField()
    letter_grade = serializers.CharField(
        required=False, help_text='Snapshot-sourced axes only.',
    )
    class_mean = serializers.FloatField(required=False)
    percentile = serializers.IntegerField(required=False)


class RadarExtremeSerializer(serializers.Serializer):
    subject = serializers.CharField()
    value = serializers.FloatField()


class RadarSourceCountSerializer(serializers.Serializer):
    snapshot = serializers.IntegerField()
    live = serializers.IntegerField()


class RadarSummarySerializer(serializers.Serializer):
    overall_mean = serializers.FloatField()
    class_overall_mean = serializers.FloatField(allow_null=True)
    strongest = RadarExtremeSerializer(allow_null=True)
    weakest = RadarExtremeSerializer(allow_null=True)
    axis_count = serializers.IntegerField(help_text='Axes drawn on the radar.')
    subject_count = serializers.IntegerField(
        help_text=(
            'Axes with lessons behind them — the ones the averages and '
            'strongest/weakest are computed over. Axes with lesson_count 0 '
            'are drawn but excluded here.'
        ),
    )
    sources = RadarSourceCountSerializer()


class AnalyticsAcademicYearSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    year = serializers.CharField()


class StudentSubjectRadarSerializer(serializers.Serializer):
    student = AnalyticsStudentSerializer()
    academic_year = AnalyticsAcademicYearSerializer(allow_null=True)
    class_group = serializers.CharField(allow_null=True)
    quarter = serializers.IntegerField(allow_null=True)
    grading = GradingNoteSerializer()
    axes = RadarAxisSerializer(many=True)
    summary = RadarSummarySerializer()


# ── Subject-grade analytics response shapes ──
#
# For apps/lesson/api/analytics_subject.py. Same rule as above: schema only.
# Scores are a percent of each assignment's own max_grade, and an unmarked
# grade is left out of the averages rather than counted as zero — the opposite
# of the topic-grade rule, because SubjectGrade.grade is nullable and a null
# means "not marked yet".


class AssignmentGradingNoteSerializer(serializers.Serializer):
    missing_grades_as = serializers.ChoiceField(
        choices=['excluded', 'zero'],
        help_text='Follows the `missing` query parameter.',
    )
    scale = serializers.CharField(
        help_text='Always "percent_of_max_grade".',
    )


class AssignmentCoverageSerializer(serializers.Serializer):
    possible_count = serializers.IntegerField(
        help_text='Assignments × students in scope.',
    )
    graded_count = serializers.IntegerField()
    graded_share = serializers.FloatField(help_text='graded_count as a percent.')


class AssignmentCategoryBlockSerializer(serializers.Serializer):
    assignment_count = serializers.IntegerField()
    graded_count = serializers.IntegerField()
    value = serializers.FloatField()


class AssignmentCategoryBreakdownSerializer(serializers.Serializer):
    lesson = AssignmentCategoryBlockSerializer()
    exam = AssignmentCategoryBlockSerializer()
    final = AssignmentCategoryBlockSerializer()


class AssignmentFiltersSerializer(serializers.Serializer):
    category = serializers.CharField(allow_null=True)
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    missing = serializers.ChoiceField(choices=['exclude', 'zero'])


class AssignmentColumnSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    category = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    max_grade = serializers.IntegerField()
    graded_count = serializers.IntegerField()


class AssignmentTrajectoryPointSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text='Subject assignment id.')
    title = serializers.CharField()
    category = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    max_grade = serializers.IntegerField()
    grade = serializers.IntegerField(
        allow_null=True, help_text='The raw mark, null when unmarked.',
    )
    percent = serializers.FloatField(
        help_text='grade as a percent of max_grade. 0.0 when unmarked.',
    )
    graded = serializers.BooleanField(
        help_text='False means unmarked — read this before reading percent.',
    )
    # Present unless include_class_stats=false.
    class_mean = serializers.FloatField(required=False)
    class_median = serializers.FloatField(required=False)
    p25 = serializers.FloatField(required=False)
    p75 = serializers.FloatField(required=False)
    class_min = serializers.FloatField(required=False)
    class_max = serializers.FloatField(required=False)
    class_size = serializers.IntegerField(required=False)
    graded_class_count = serializers.IntegerField(
        required=False, allow_null=True,
        help_text='Classmates with a mark. Null under missing=zero.',
    )
    rank = serializers.IntegerField(
        required=False, help_text='0 when this student has no mark.',
    )


class AssignmentTrajectorySummarySerializer(serializers.Serializer):
    assignment_count = serializers.IntegerField()
    graded_count = serializers.IntegerField()
    student_mean = serializers.FloatField()
    class_mean = serializers.FloatField(allow_null=True)
    delta = serializers.FloatField(allow_null=True)
    trend_slope = serializers.FloatField(
        help_text='Least-squares percentage points per assignment.',
    )
    by_category = AssignmentCategoryBreakdownSerializer()
    coverage = AssignmentCoverageSerializer()


class StudentAssignmentTrajectorySerializer(serializers.Serializer):
    student = AnalyticsStudentSerializer()
    offering = AnalyticsOfferingSerializer()
    filters = AssignmentFiltersSerializer()
    grading = AssignmentGradingNoteSerializer()
    points = AssignmentTrajectoryPointSerializer(many=True)
    summary = AssignmentTrajectorySummarySerializer()


class AssignmentHeatmapSerializer(serializers.Serializer):
    offering = AnalyticsOfferingSerializer()
    filters = AssignmentFiltersSerializer()
    grading = AssignmentGradingNoteSerializer()
    scale = HeatmapScaleSerializer(help_text='Always 0–100: cells are percentages.')
    students = AnalyticsStudentSerializer(many=True)
    assignments = AssignmentColumnSerializer(many=True)
    matrix = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField()),
        help_text=(
            'matrix[i][j] = students[i] on assignments[j], as a percent. '
            '0.0 where unmarked — check graded[i][j].'
        ),
    )
    graded = serializers.ListField(
        child=serializers.ListField(child=serializers.BooleanField()),
        help_text='Whether each cell holds a real mark.',
    )
    raw_grades = serializers.ListField(
        child=serializers.ListField(
            child=serializers.IntegerField(allow_null=True),
        ),
        help_text='The marks as entered, in the assignment\'s own points.',
    )
    row_means = serializers.ListField(child=serializers.FloatField())
    column_means = serializers.ListField(child=serializers.FloatField())
    coverage = AssignmentCoverageSerializer()
    class_size = serializers.IntegerField()
    assignment_count = serializers.IntegerField()
    truncated = serializers.BooleanField(
        help_text='True when older assignments were dropped; narrow by date.',
    )


class AssignmentSummaryFiltersSerializer(AssignmentFiltersSerializer):
    quarter = serializers.IntegerField(allow_null=True)


class AssignmentAxisSerializer(serializers.Serializer):
    offering_id = serializers.IntegerField()
    subject_id = serializers.IntegerField()
    subject = serializers.CharField()
    language_group = serializers.CharField()
    value = serializers.FloatField()
    assignment_count = serializers.IntegerField(
        help_text='Read this before value: 0 means the subject set no work.',
    )
    graded_count = serializers.IntegerField()
    by_category = AssignmentCategoryBreakdownSerializer()
    class_mean = serializers.FloatField(required=False)
    percentile = serializers.IntegerField(required=False)


class AssignmentSummaryTotalsSerializer(serializers.Serializer):
    overall_mean = serializers.FloatField()
    class_overall_mean = serializers.FloatField(allow_null=True)
    strongest = RadarExtremeSerializer(allow_null=True)
    weakest = RadarExtremeSerializer(allow_null=True)
    axis_count = serializers.IntegerField()
    subject_count = serializers.IntegerField(
        help_text='Axes with assignments behind them — what the averages use.',
    )
    assignment_count = serializers.IntegerField()
    graded_count = serializers.IntegerField()
    by_category = AssignmentCategoryBreakdownSerializer()


class AnalyticsClassGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    grade_level = serializers.IntegerField(allow_null=True)
    letter = serializers.CharField()
    academic_year = serializers.CharField(allow_null=True)


class StudentAssignmentSummarySerializer(serializers.Serializer):
    student = AnalyticsStudentSerializer()
    academic_year = AnalyticsAcademicYearSerializer(allow_null=True)
    class_group = AnalyticsClassGroupSerializer(allow_null=True)
    filters = AssignmentSummaryFiltersSerializer()
    grading = AssignmentGradingNoteSerializer()
    axes = AssignmentAxisSerializer(many=True)
    summary = AssignmentSummaryTotalsSerializer()


# ── Attendance analytics response shapes ──
#
# For apps/lesson/api/analytics_attendance.py. Schema only, as above. An
# unrecorded slot is never an absence: rates are present / (present + absent)
# over the rows that exist, and `recorded` says how many that was.


class AttendanceCountingNoteSerializer(serializers.Serializer):
    unrecorded_as = serializers.CharField(help_text='Always "excluded".')
    rate = serializers.CharField(help_text='Always "present / (present + absent)".')


class AttendanceCountsSerializer(serializers.Serializer):
    recorded = serializers.IntegerField()
    present = serializers.IntegerField()
    absent = serializers.IntegerField()
    attendance_rate = serializers.FloatField(
        help_text='0.0 when nothing was recorded — read `recorded` first.',
    )


class AttendanceFiltersSerializer(serializers.Serializer):
    academic_year = serializers.IntegerField(allow_null=True)
    quarter = serializers.IntegerField(
        allow_null=True, help_text="The schedule's own quarter, not a date window.",
    )
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)


class StudentAttendanceFiltersSerializer(AttendanceFiltersSerializer):
    offering = serializers.IntegerField(allow_null=True)


class ClassAttendanceFiltersSerializer(AttendanceFiltersSerializer):
    at_risk_below = serializers.FloatField()


class SubjectAttendanceBlockSerializer(AttendanceCountsSerializer):
    offering_id = serializers.IntegerField(
        allow_null=True, help_text='Null for a schedule with no offering.',
    )
    subject = serializers.CharField(
        help_text="The subject's name, or the description of an offering-less entry.",
    )


class WeekdayAttendanceBlockSerializer(AttendanceCountsSerializer):
    weekday = serializers.IntegerField(help_text='0 = Monday … 6 = Sunday.')


class MonthAttendanceBlockSerializer(AttendanceCountsSerializer):
    month = serializers.CharField(allow_null=True, help_text='YYYY-MM.')


class AttendanceClassComparisonSerializer(serializers.Serializer):
    class_size = serializers.IntegerField()
    class_attendance_rate = serializers.FloatField(
        help_text='Pooled over every row of the class.',
    )
    class_mean_rate = serializers.FloatField(
        help_text='Mean of the per-student rates — what the rank is taken over.',
    )
    rank = serializers.IntegerField(help_text='1-based, best first; ties share.')
    percentile = serializers.IntegerField()
    delta = serializers.FloatField(
        help_text="This student's rate minus class_mean_rate.",
    )


class StudentAttendanceSummarySerializer(serializers.Serializer):
    student = AnalyticsStudentSerializer()
    academic_year = AnalyticsAcademicYearSerializer(allow_null=True)
    class_group = AnalyticsClassGroupSerializer(allow_null=True)
    filters = StudentAttendanceFiltersSerializer()
    counting = AttendanceCountingNoteSerializer()
    totals = AttendanceCountsSerializer()
    by_subject = SubjectAttendanceBlockSerializer(many=True)
    by_weekday = WeekdayAttendanceBlockSerializer(
        many=True, help_text='Always seven entries, Monday first.',
    )
    by_month = MonthAttendanceBlockSerializer(many=True)
    class_comparison = AttendanceClassComparisonSerializer(allow_null=True)


class AttendanceSlotSerializer(serializers.Serializer):
    key = serializers.CharField(help_text='"<date>:<session_id>".')
    date = serializers.DateField()
    session_id = serializers.IntegerField()
    time_start = serializers.TimeField(help_text='When the slot starts, HH:MM:SS.')
    time_end = serializers.TimeField()
    weekday = serializers.IntegerField()
    quarter = serializers.IntegerField()


class OfferingAttendanceHeatmapSerializer(serializers.Serializer):
    offering = AnalyticsOfferingSerializer()
    filters = AttendanceFiltersSerializer()
    counting = AttendanceCountingNoteSerializer()
    legend = serializers.ListField(
        child=serializers.CharField(allow_null=True),
        help_text='The three cell values: "present", "absent", null.',
    )
    students = AnalyticsStudentSerializer(many=True)
    slots = AttendanceSlotSerializer(many=True)
    matrix = serializers.ListField(
        child=serializers.ListField(
            child=serializers.CharField(allow_null=True),
        ),
        help_text=(
            'matrix[i][j] = students[i] at slots[j]: "present", "absent", or '
            'null where nothing was registered. Null is not an absence.'
        ),
    )
    row_summary = AttendanceCountsSerializer(many=True)
    column_summary = AttendanceCountsSerializer(many=True)
    totals = AttendanceCountsSerializer()
    class_size = serializers.IntegerField()
    slot_count = serializers.IntegerField()
    truncated = serializers.BooleanField(
        help_text='True when older slots were dropped; narrow by date or quarter.',
    )


class StudentAttendanceBlockSerializer(AttendanceCountsSerializer):
    student = AnalyticsStudentSerializer()
    rank = serializers.IntegerField(help_text='1-based, best first; ties share.')


class ClassAttendanceTotalsSerializer(AttendanceCountsSerializer):
    class_size = serializers.IntegerField()
    mean_student_rate = serializers.FloatField(
        help_text='Mean of the per-student rates, unweighted by row count.',
    )


class ClassGroupAttendanceOverviewSerializer(serializers.Serializer):
    class_group = AnalyticsClassGroupSerializer()
    academic_year = AnalyticsAcademicYearSerializer(allow_null=True)
    filters = ClassAttendanceFiltersSerializer()
    counting = AttendanceCountingNoteSerializer()
    totals = ClassAttendanceTotalsSerializer()
    students = StudentAttendanceBlockSerializer(
        many=True, help_text='Best attendance first.',
    )
    by_subject = SubjectAttendanceBlockSerializer(many=True)
    by_weekday = WeekdayAttendanceBlockSerializer(many=True)
    by_month = MonthAttendanceBlockSerializer(many=True)
    at_risk = StudentAttendanceBlockSerializer(
        many=True, help_text='Below at_risk_below, and with something recorded.',
    )
