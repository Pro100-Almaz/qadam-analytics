from rest_framework import serializers

from apps.authentication.api.serializers import UserSerializer
from apps.authentication.models import (
    Student, Teacher, Parent,
    PsychologicalState, PsychologicalStateTemplates,
)
from apps.home.models import (
    AcademicYear, GradeLevel, ClassGroup,
    Subject, SubjectOffering, TeachingAssignment, Enrollment,
)
from apps.lesson.models import Lesson, TopicGrade, Topic


class AcademicYearSerializer(serializers.ModelSerializer):
    current_quarter = serializers.IntegerField(read_only=True)
    quarters = serializers.ListField(read_only=True)

    class Meta:
        model = AcademicYear
        fields = [
            'id', 'year', 'is_active', 'archived',
            'q1_start', 'q1_end', 'q2_start', 'q2_end',
            'q3_start', 'q3_end', 'q4_start', 'q4_end',
            'current_quarter', 'quarters',
        ]


class GradeLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeLevel
        fields = ['id', 'number']


class ClassGroupSerializer(serializers.ModelSerializer):
    grade_level = GradeLevelSerializer(read_only=True)
    academic_year = AcademicYearSerializer(read_only=True)
    display_name = serializers.CharField(source='__str__', read_only=True)

    class Meta:
        model = ClassGroup
        fields = ['id', 'letter', 'grade_level', 'academic_year', 'display_name']


class SubjectSerializer(serializers.ModelSerializer):
    added_by = UserSerializer(read_only=True)

    class Meta:
        model = Subject
        fields = ['id', 'name', 'language_group', 'status', 'added_by']


class SubjectOfferingSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_group = ClassGroupSerializer(read_only=True)
    academic_year = AcademicYearSerializer(read_only=True)

    class Meta:
        model = SubjectOffering
        fields = [
            'id', 'subject', 'class_group', 'academic_year',
            'grading_strategy', 'max_points',
        ]


class TeachingAssignmentSerializer(serializers.ModelSerializer):
    offering = SubjectOfferingSerializer(read_only=True)

    class Meta:
        model = TeachingAssignment
        fields = ['id', 'offering', 'teacher', 'role']


class EnrollmentSerializer(serializers.ModelSerializer):
    class_group = ClassGroupSerializer(read_only=True)
    academic_year = AcademicYearSerializer(read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            'id', 'student', 'class_group', 'academic_year',
            'status', 'start_date', 'end_date',
        ]


# ── Student serializers ──

class StudentListSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    current_class_group = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ['id', 'user', 'school_group', 'academic_year', 'current_class_group']

    def get_current_class_group(self, obj):
        class_group = getattr(obj, 'classroom', None)
        if class_group:
            return ClassGroupSerializer(class_group).data
        enrollment = obj.get_current_enrollment()
        if enrollment:
            return ClassGroupSerializer(enrollment.class_group).data
        return None


class StudentDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    current_class_group = serializers.SerializerMethodField()
    offerings = serializers.SerializerMethodField()
    subject_quarter_grades = serializers.SerializerMethodField()
    total_quarter_grades = serializers.SerializerMethodField()
    cumulative_subject_grades = serializers.SerializerMethodField()
    student_total_grade = serializers.SerializerMethodField()
    psychological_states = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'id', 'user', 'school_group', 'academic_year',
            'current_class_group', 'offerings',
            'subject_quarter_grades', 'total_quarter_grades',
            'cumulative_subject_grades', 'student_total_grade',
            'psychological_states',
        ]

    def _get_grade_context(self, student):
        if hasattr(self, '_grade_cache'):
            return self._grade_cache

        from apps.home.models import SubjectOffering
        from apps.lesson.models import Lesson
        from apps.lesson.services import get_cached_grades_bulk
        from apps.home.repo.students import calculate_quarter_grade, grade_identifier

        enrollment = student.get_current_enrollment()
        if not enrollment:
            self._grade_cache = {
                'offerings': [],
                'subject_quarter_grades': {},
                'total_quarter_grades': {},
                'cumulative_subject_grades': {},
                'student_total_grade': 0,
            }
            return self._grade_cache

        offerings = list(SubjectOffering.objects.filter(
            class_group=enrollment.class_group,
            academic_year=enrollment.academic_year,
        ).select_related('subject'))

        lessons = list(Lesson.objects.filter(offering__in=offerings))
        grades_map = get_cached_grades_bulk(lessons, [student])

        subject_quarter_grades = {}
        for quarter in [1, 2, 3, 4]:
            subject_quarter_grades[quarter] = {}
            for offering in offerings:
                quarter_lessons = [
                    l for l in lessons
                    if l.offering_id == offering.id and l.quarter == quarter
                ]
                if quarter_lessons:
                    lesson_grades = [
                        grades_map.get((l.id, student.id), 0) for l in quarter_lessons
                    ]
                    grade = sum(lesson_grades) / len(lesson_grades)
                else:
                    grade = 0
                subject_quarter_grades[quarter][offering.subject.name] = grade

        num_subjects = len(offerings)
        total_quarter_grades = {}
        student_total_grade = 0
        for quarter in [1, 2, 3, 4]:
            quarter_sum = sum(subject_quarter_grades[quarter].values())
            avg = round(quarter_sum / num_subjects, 1) if num_subjects > 0 else 0
            student_total_grade += avg / 4
            total_quarter_grades[quarter] = grade_identifier(avg)

        cumulative_subject_grades = {}
        for offering in offerings:
            total = sum(
                subject_quarter_grades[q].get(offering.subject.name, 0)
                for q in [1, 2, 3, 4]
            )
            cumulative_subject_grades[offering.subject.name] = round(total / 4, 1)

        self._grade_cache = {
            'offerings': offerings,
            'subject_quarter_grades': subject_quarter_grades,
            'total_quarter_grades': total_quarter_grades,
            'cumulative_subject_grades': cumulative_subject_grades,
            'student_total_grade': round(student_total_grade, 2),
        }
        return self._grade_cache

    def get_current_class_group(self, obj):
        enrollment = obj.get_current_enrollment()
        if enrollment:
            return ClassGroupSerializer(enrollment.class_group).data
        return None

    def get_offerings(self, obj):
        ctx = self._get_grade_context(obj)
        return SubjectOfferingSerializer(ctx['offerings'], many=True).data

    def get_subject_quarter_grades(self, obj):
        ctx = self._get_grade_context(obj)
        result = {}
        for quarter, subjects in ctx['subject_quarter_grades'].items():
            result[str(quarter)] = {
                name: round(grade, 1) for name, grade in subjects.items()
            }
        return result

    def get_total_quarter_grades(self, obj):
        ctx = self._get_grade_context(obj)
        return {str(k): v for k, v in ctx['total_quarter_grades'].items()}

    def get_cumulative_subject_grades(self, obj):
        ctx = self._get_grade_context(obj)
        return ctx['cumulative_subject_grades']

    def get_student_total_grade(self, obj):
        ctx = self._get_grade_context(obj)
        return ctx['student_total_grade']

    def get_psychological_states(self, obj):
        states = PsychologicalState.objects.filter(
            student=obj
        ).select_related('added_by').order_by('name', '-time_added')

        seen = set()
        latest_states = []
        history = {}
        for state in states:
            if state.name not in seen:
                seen.add(state.name)
                latest_states.append(state)
                history[state.name] = []
            else:
                history[state.name].append(state)

        def _record(r):
            return {
                'id': r.id,
                'name': r.name,
                'score': r.score,
                'comment': r.comment or '',
                'added_by': (
                    r.added_by.get_full_name() or r.added_by.username
                ) if r.added_by else '',
                'time_added': r.time_added.isoformat() if r.time_added else None,
            }

        return {
            'current': [_record(s) for s in latest_states],
            'history': {
                name: list(reversed(
                    [_record(latest_states[i])]
                    + [_record(h) for h in history[name]]
                ))
                for i, name in enumerate(
                    s.name for s in latest_states
                )
            },
        }


class StudentProfileUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    address = serializers.CharField(required=False, allow_blank=True)
    school_group = serializers.IntegerField(required=False, allow_null=True)
    academic_year = serializers.IntegerField(required=False, allow_null=True)
    class_group = serializers.IntegerField(required=False, allow_null=True)


# ── Teacher serializers ──

class TeacherListSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Teacher
        fields = [
            'id', 'user', 'gender', 'academic_degree',
            'employment_type', 'occupation', 'working_hours',
        ]


class TeacherDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    assignments = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()

    class Meta:
        model = Teacher
        fields = [
            'id', 'user', 'gender', 'academic_degree',
            'employment_type', 'occupation', 'working_hours',
            'assignments', 'subjects',
        ]

    def get_assignments(self, obj):
        assignments = TeachingAssignment.objects.filter(
            teacher=obj
        ).select_related(
            'offering', 'offering__subject', 'offering__class_group',
        )
        return TeachingAssignmentSerializer(assignments, many=True).data

    def get_subjects(self, obj):
        subject_ids = TeachingAssignment.objects.filter(
            teacher=obj
        ).values_list('offering__subject_id', flat=True).distinct()
        subjects = Subject.objects.filter(id__in=subject_ids)
        return SubjectSerializer(subjects, many=True).data


class TeacherProfileUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    address = serializers.CharField(required=False, allow_blank=True)
    gender = serializers.ChoiceField(choices=Teacher.GENDER_CHOICES, required=False)
    academic_degree = serializers.CharField(required=False, allow_blank=True)
    employment_type = serializers.ChoiceField(
        choices=Teacher.EMPLOYMENT_TYPE_CHOICES, required=False
    )
    occupation = serializers.CharField(required=False, allow_blank=True)


# ── Subject serializers ──

class SubjectCreateSerializer(serializers.Serializer):
    name = serializers.CharField()
    language_group = serializers.ChoiceField(choices=Subject.LANGUAGE_CHOICES)
    status = serializers.ChoiceField(choices=Subject.STATUS_CHOICES, default='active')
    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all(), required=False, allow_null=True
    )
    class_groups = serializers.PrimaryKeyRelatedField(
        queryset=ClassGroup.objects.all(), many=True, required=False
    )

    def create(self, validated_data):
        academic_year = validated_data.pop('academic_year', None)
        class_groups = validated_data.pop('class_groups', [])
        user = self.context['request'].user

        subject = Subject.objects.create(added_by=user, **validated_data)

        offerings_created = 0
        if academic_year and class_groups:
            for class_group in class_groups:
                offering, created = SubjectOffering.objects.get_or_create(
                    subject=subject,
                    class_group=class_group,
                    academic_year=academic_year,
                )
                if created:
                    offerings_created += 1
                    if user.is_teacher():
                        try:
                            teacher = Teacher.objects.get(user=user)
                            TeachingAssignment.objects.get_or_create(
                                offering=offering,
                                teacher=teacher,
                                defaults={'role': 'primary'},
                            )
                        except Teacher.DoesNotExist:
                            pass

        subject._offerings_created = offerings_created
        return subject


class SubjectDetailSerializer(serializers.ModelSerializer):
    added_by = UserSerializer(read_only=True)
    offerings = serializers.SerializerMethodField()
    students_count = serializers.SerializerMethodField()
    lessons_count = serializers.SerializerMethodField()
    primary_teacher = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = [
            'id', 'name', 'language_group', 'status', 'added_by',
            'offerings', 'students_count', 'lessons_count', 'primary_teacher',
        ]

    def _get_context(self, obj):
        if hasattr(self, '_detail_cache'):
            return self._detail_cache

        from apps.lesson.models import Lesson

        current_year = AcademicYear.objects.filter(is_active=True).first()
        if not current_year:
            current_year = AcademicYear.objects.order_by('-year').first()

        offerings = list(
            SubjectOffering.objects.filter(
                subject=obj, academic_year=current_year
            ).select_related('class_group')
        ) if current_year else []

        student_ids_seen = set()
        students = []
        for offering in offerings:
            enrollments = Enrollment.objects.filter(
                class_group=offering.class_group,
                academic_year=offering.academic_year,
                status='active',
            ).select_related('student', 'student__user')
            for e in enrollments:
                if e.student.id not in student_ids_seen:
                    student_ids_seen.add(e.student.id)
                    students.append(e.student)

        total_lessons = list(Lesson.objects.filter(offering__in=offerings))

        primary_teacher = None
        if offerings:
            primary_teacher = offerings[0].get_primary_teacher()

        self._detail_cache = {
            'offerings': offerings,
            'students': students,
            'total_lessons': total_lessons,
            'primary_teacher': primary_teacher,
        }
        return self._detail_cache

    def get_offerings(self, obj):
        ctx = self._get_context(obj)
        return SubjectOfferingSerializer(ctx['offerings'], many=True).data

    def get_students_count(self, obj):
        ctx = self._get_context(obj)
        return len(ctx['students'])

    def get_lessons_count(self, obj):
        ctx = self._get_context(obj)
        return len(ctx['total_lessons'])

    def get_primary_teacher(self, obj):
        ctx = self._get_context(obj)
        teacher = ctx['primary_teacher']
        if teacher:
            return TeacherListSerializer(teacher).data
        return None


class SubjectStatusSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['archive', 'activate', 'plan'])


# ── Dashboard ──

class DashboardStatsSerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    total_teachers = serializers.IntegerField()
    total_classes = serializers.IntegerField()


# ── Psychological State ──

class PsychologicalStateCreateSerializer(serializers.Serializer):
    state_name = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True)
    score = serializers.IntegerField(min_value=1, max_value=5)


class PsychologicalStateTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologicalStateTemplates
        fields = ['id', 'name', 'comment']


# ── Student Self-Service ──

class StudentMySubjectSerializer(serializers.Serializer):
    offering_id = serializers.IntegerField()
    subject_id = serializers.IntegerField()
    subject_name = serializers.CharField()
    language = serializers.CharField()
    teacher = serializers.DictField(allow_null=True)
    class_group_name = serializers.CharField()
    student_grade = serializers.FloatField()
    quarter_grades = serializers.DictField()


class StudentMyTeacherSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)
    email = serializers.CharField()
    subjects = serializers.ListField(child=serializers.CharField())


class StudentClassmateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)
    email = serializers.CharField()
    student_total_grade = serializers.FloatField()


# ── Parent Self-Service ──

class ParentChildSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    full_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)
    class_group_name = serializers.CharField(allow_null=True)
    school_group = serializers.CharField(allow_null=True)
    student_total_grade = serializers.FloatField()
    quarter_grades = serializers.DictField()


class ParentChildDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    full_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)
    email = serializers.CharField()
    phone_number = serializers.CharField(allow_null=True)
    class_group_name = serializers.CharField(allow_null=True)
    school_group = serializers.CharField(allow_null=True)
    student_total_grade = serializers.FloatField()
    quarter_grades = serializers.DictField()
    subjects = serializers.ListField()


class ParentTeacherDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)
    email = serializers.CharField()
    subjects = serializers.ListField(child=serializers.CharField())
    children = serializers.ListField(child=serializers.CharField())


class ParentChildBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ['id', 'full_name', 'avatar']

    def get_full_name(self, obj):
        return str(obj.user)

    def get_avatar(self, obj):
        return obj.user.avatar.url if obj.user.avatar else None


class ParentTeacherBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()

    class Meta:
        model = Teacher
        fields = ['id', 'full_name', 'avatar', 'email', 'occupation']

    def get_full_name(self, obj):
        return str(obj.user)

    def get_avatar(self, obj):
        return obj.user.avatar.url if obj.user.avatar else None

    def get_email(self, obj):
        return obj.user.email


class CommentSerializer(serializers.Serializer):
    topic_title = serializers.CharField()
    comment = serializers.CharField(allow_null=True)


class ParentChildLessonSerializer(serializers.Serializer):
    lesson_id = serializers.IntegerField()
    lesson_title = serializers.CharField()
    lesson_date = serializers.DateField()
    order = serializers.IntegerField()
    quarter = serializers.IntegerField()
    status = serializers.CharField()
    earned_points = serializers.FloatField(allow_null=True)
    comments = CommentSerializer(allow_null=True, many=True)


class ParentChildSubjectDetailSerializer(serializers.Serializer):
    child = ParentChildBriefSerializer()
    teacher = ParentTeacherBriefSerializer()
    subject_id = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()
    language_group = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    class_group_name = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    cumulative_grade = serializers.SerializerMethodField()
    quarter_grades = serializers.SerializerMethodField()
    lessons = serializers.SerializerMethodField()

    def get_subject_id(self, obj):
        return obj.get('subject').id

    def get_subject_name(self, obj):
        return obj.get('subject').name

    def get_language_group(self, obj):
        return obj.get('subject').language_group

    def get_status(self, obj):
        return obj.get('subject').status

    def get_class_group_name(self, obj):
        return str(obj.get('class_group'))

    def get_academic_year(self, obj):
        return str(obj.get('class_group').academic_year)

    def _get_quarter_grades(self, obj):
        if hasattr(self, '_quarter_grades_cache'):
            return self._quarter_grades_cache

        grades_map = Lesson.calculate_grades_bulk(
            obj.get('lessons'),
            [obj.get('child')]
        ) if obj.get('lessons') else {}

        self._quarter_grades_cache = {}
        for quarter in [1, 2, 3, 4]:
            self._quarter_grades_cache[quarter] = {}

            quarter_lessons = [l for l in obj.get('lessons') if l.quarter == quarter]
            if quarter_lessons:
                lesson_grades = [grades_map.get((l.id, obj.get('child').id), 0) for l in quarter_lessons]
                grade = sum(lesson_grades) / len(lesson_grades)
            else:
                grade = 0
            self._quarter_grades_cache[quarter] = grade

        return self._quarter_grades_cache

    def get_cumulative_grade(self, obj):
        grades = self._get_quarter_grades(obj)
        total = sum(grades[q] for q in [1, 2, 3, 4])
        return round(total / 4, 1)

    def get_quarter_grades(self, obj):
        return self._get_quarter_grades(obj)

    def get_lessons(self, obj):
        student = obj.get('child')
        lessons = obj.get('lessons')

        all_topic_grades = TopicGrade.objects.filter(
            topic__lesson__in=lessons,
            student=obj.get('child'),
        ).values('topic_id', 'grade', 'comment', 'comment_selected', 'topic__lesson_id', 'topic__title')

        grades_map = {}
        topic_grades_by_lesson = {}
        for tg in all_topic_grades:
            grades_map[(tg['topic_id'], tg['topic__lesson_id'])] = tg['grade']
            lesson_map = topic_grades_by_lesson.setdefault(tg['topic__lesson_id'], {})
            lesson_map[tg['topic_id']] = {
                'grade': tg['grade'],
                'comment': tg['comment'] or '',
                'comment_selected': tg['comment_selected'],
            }

        # Subtopic ids per parent topic for comment aggregation
        parent_topics = Topic.objects.filter(
            lesson__in=lessons, parent__isnull=True
        ).prefetch_related('subtopics')
        topic_subtopic_ids = {
            t.id: [s.id for s in t.subtopics.all()] for t in parent_topics
        }
        topic_titles = { t.id: t.title for t in parent_topics }

        result = {}
        bulk_grades = Lesson.calculate_grades_bulk(lessons, [student])
        for lesson in lessons:
            key = str(lesson.id)
            result[key] = {
                'grade_total': round(bulk_grades[(lesson.id, student.id)], 1),
            }
            per_topic = topic_grades_by_lesson.get(lesson.id, {})
            result[key].update({str(k): v for k, v in per_topic.items()})
            # Resolve comment display for parent topics that have subtopics
            comments = []
            for topic_id, subtopic_ids in topic_subtopic_ids.items():
                entry = result[key].get(str(topic_id))
                if not isinstance(entry, dict):
                    continue
                selected_sub_comment = None

                if not subtopic_ids:
                    selected_sub_comment = per_topic.get(topic_id, {}).get('comment', '')
                for sub_id in subtopic_ids:
                    sub_entry = per_topic.get(sub_id, {})
                    if sub_entry.get('comment_selected') and sub_entry.get('comment'):
                        selected_sub_comment = sub_entry['comment']
                        break
                if selected_sub_comment:
                    entry['comment'] = selected_sub_comment
                elif not entry.get('comment'):
                    sub_comments = [
                        per_topic[sub_id]['comment']
                        for sub_id in subtopic_ids
                        if per_topic.get(sub_id, {}).get('comment')
                    ]
                    if sub_comments:
                        entry['comment'] = '. '.join(sub_comments)
                comments.append({"topic_title": topic_titles.get(topic_id, ""), "comment": entry['comment']})
            result[key]["comment_total"] = comments

        data = [
            {
                "lesson_id": lesson.id,
                "lesson_title": lesson.title,
                "lesson_date": lesson.date,
                "order": lesson.order,
                "quarter": lesson.quarter,
                "status": lesson.status,
                "earned_points": result[str(lesson.id)].get('grade_total', None),
                "comments": result[str(lesson.id)].get('comment_total', [])
            }
            for lesson in lessons
        ]
        return ParentChildLessonSerializer(data, many=True).data
