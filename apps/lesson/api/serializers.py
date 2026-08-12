from rest_framework import serializers

from apps.lesson.models import (
    Lesson, Topic, TopicGrade, MergedLessonComment,
    SubjectSchedule, ScheduleSession, ScheduleAttendance,
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
        fields = ['id', 'schedule', 'order', 'weekday']
        read_only_fields = ['schedule']


class ScheduleSessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleSession
        fields = ['order', 'weekday']

    def validate_order(self, value):
        if not (1 <= value <= 12):
            raise serializers.ValidationError('Order must be between 1 and 12.')
        return value

    def validate_weekday(self, value):
        if not (0 <= value <= 6):
            raise serializers.ValidationError(
                'Weekday must be between 0 (Monday) and 6 (Sunday).'
            )
        return value

    def validate(self, attrs):
        """Reject a second session in the same slot of the same schedule."""
        schedule = self.context['schedule']
        order = attrs.get('order', getattr(self.instance, 'order', None))
        weekday = attrs.get('weekday', getattr(self.instance, 'weekday', None))

        clash = ScheduleSession.objects.filter(
            schedule=schedule, order=order, weekday=weekday,
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                'This schedule already has a session in that weekday/order slot.'
            )
        return attrs


# ── Subject schedule serializers ──

class OtherScheduleSessionSerializer(serializers.ModelSerializer):
    """A slot in the class group's timetable owned by a different subject."""
    offering_id = serializers.IntegerField(source='schedule.offering_id', read_only=True)
    subject_name = serializers.CharField(
        source='schedule.offering.subject.name', read_only=True,
    )

    class Meta:
        model = ScheduleSession
        fields = ['id', 'schedule', 'offering_id', 'subject_name', 'order', 'weekday']


class SubjectScheduleSerializer(serializers.ModelSerializer):
    offering = OfferingMinimalSerializer(read_only=True)
    offering_id = serializers.IntegerField(read_only=True)
    sessions = serializers.SerializerMethodField()
    other_sessions = serializers.SerializerMethodField()

    class Meta:
        model = SubjectSchedule
        fields = [
            'id', 'offering', 'offering_id', 'quarter',
            'sessions', 'other_sessions',
        ]

    def get_sessions(self, obj):
        sessions = sorted(obj.sessions.all(), key=lambda s: (s.weekday, s.order))
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
        )
    )

    class Meta:
        model = SubjectSchedule
        fields = ['offering', 'quarter']

    def validate_quarter(self, value):
        if not (1 <= value <= 4):
            raise serializers.ValidationError('Quarter must be between 1 and 4.')
        return value


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
