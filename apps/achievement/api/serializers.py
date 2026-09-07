from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.achievement.models import (
    Achievement,
    Attachment,
    Club,
    ClubAttendance,
    ClubEntry,
    ClubSession,
    ReadingEntry,
)
from apps.authentication.models import ClubManager, Student
from apps.home.models import AcademicYear, Subject
from core.permissions import is_admin_role

# ── Shared nested serializers ──

class _StudentBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['id', 'file', 'file_type', 'original_name', 'created_at']
        read_only_fields = ['id', 'created_at']


# ── Achievement serializers ──

class AchievementListSerializer(serializers.ModelSerializer):
    student = _StudentBriefSerializer(read_only=True)
    academic_year = serializers.StringRelatedField(read_only=True)
    subject_name = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Achievement
        fields = [
            'id', 'student', 'academic_year', 'category',
            'subject_name', 'award_type', 'place',
            'role', 'duration', 'description',
            'certificate', 'attachments', 'created_at', 'updated_at',
        ]

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None


class AchievementDetailSerializer(AchievementListSerializer):
    """Same shape as list — exposes all fields."""
    pass


class AchievementCreateSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    academic_year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())
    category = serializers.ChoiceField(choices=Achievement.CATEGORY_CHOICES)
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), required=False, allow_null=True
    )
    award_type = serializers.CharField(max_length=255, required=False, allow_blank=True)
    place = serializers.CharField(max_length=255, required=False, allow_blank=True)
    role = serializers.CharField(max_length=255, required=False, allow_blank=True)
    duration = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    certificate = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        category = attrs.get('category')
        role = attrs.get('role', '')

        if category == 'extracurricular' and not role:
            raise serializers.ValidationError(
                {'role': 'Role is required for extracurricular achievements.'}
            )
        return attrs

    def create(self, validated_data):
        return Achievement.objects.create(**validated_data)


class AchievementUpdateSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(), required=False
    )
    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all(), required=False
    )
    category = serializers.ChoiceField(
        choices=Achievement.CATEGORY_CHOICES, required=False
    )
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), required=False, allow_null=True
    )
    award_type = serializers.CharField(max_length=255, required=False, allow_blank=True)
    place = serializers.CharField(max_length=255, required=False, allow_blank=True)
    role = serializers.CharField(max_length=255, required=False, allow_blank=True)
    duration = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    certificate = serializers.FileField(required=False, allow_null=True)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ── ReadingEntry serializers ──

class ReadingEntrySerializer(serializers.ModelSerializer):
    student = _StudentBriefSerializer(read_only=True)
    academic_year = serializers.StringRelatedField(read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = ReadingEntry
        fields = [
            'id', 'student', 'academic_year',
            'title', 'cover', 'month', 'pages_read', 'test_score',
            'attachments', 'created_at',
        ]


class ReadingEntryCreateSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    academic_year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())
    title = serializers.CharField(max_length=500)
    cover = serializers.ImageField(required=False, allow_null=True)
    month = serializers.IntegerField(min_value=1, max_value=12)
    pages_read = serializers.IntegerField(min_value=0, default=0)
    test_score = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=100
    )

    def create(self, validated_data):
        return ReadingEntry.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ── ClubEntry serializers ──

class ClubEntrySerializer(serializers.ModelSerializer):
    student = _StudentBriefSerializer(read_only=True)
    academic_year = serializers.StringRelatedField(read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = ClubEntry
        fields = [
            'id', 'student', 'academic_year', 'month',
            'club_name', 'plan', 'criteria',
            'total_sessions', 'attended_sessions', 'comments',
            'attachments', 'created_at',
        ]


class ClubEntryCreateSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    academic_year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())
    month = serializers.IntegerField(min_value=1, max_value=12)
    club_name = serializers.CharField(max_length=255)
    plan = serializers.CharField(required=False, allow_blank=True)
    criteria = serializers.CharField(required=False, allow_blank=True)
    total_sessions = serializers.IntegerField(min_value=0, default=0)
    attended_sessions = serializers.IntegerField(min_value=0, default=0)
    comments = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        total = attrs.get('total_sessions', 0)
        attended = attrs.get('attended_sessions', 0)
        if attended > total:
            raise serializers.ValidationError(
                {'attended_sessions': 'Attended sessions cannot exceed total sessions.'}
            )
        return attrs

    def create(self, validated_data):
        return ClubEntry.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ── Managed clubs ──

class ClubAcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ['id', 'year']


class ClubAttachmentSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='original_name')
    url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ['id', 'name', 'url', 'file_type']

    @extend_schema_field(OpenApiTypes.URI)
    def get_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class ClubSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubSession
        fields = ['id', 'weekday', 'start_time', 'end_time', 'location']


class ClubStudentSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    full_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ['id', 'first_name', 'last_name', 'full_name', 'class_name', 'avatar']

    @extend_schema_field(OpenApiTypes.STR)
    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @extend_schema_field(OpenApiTypes.STR)
    def get_class_name(self, obj):
        enrollments = getattr(obj, 'club_enrollments', None)
        if enrollments is None:
            enrollment = obj.enrollments.filter(status='active').select_related(
                'class_group__grade_level', 'academic_year'
            ).order_by('-academic_year__is_active', '-academic_year__year').first()
        else:
            enrollment = enrollments[0] if enrollments else None
        if not enrollment or not enrollment.class_group:
            return None
        group = enrollment.class_group
        grade = group.grade_level.number if group.grade_level else ''
        return f'{grade}{group.letter}'

    @extend_schema_field(OpenApiTypes.URI)
    def get_avatar(self, obj):
        avatar = obj.user.avatar
        if not avatar or avatar.name == 'avatars/default/default-user.jpeg':
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(avatar.url)
        return avatar.url


class ClubSerializer(serializers.ModelSerializer):
    club_name = serializers.CharField(source='name')
    academic_year = ClubAcademicYearSerializer(read_only=True)
    status = serializers.CharField(read_only=True)
    member_count = serializers.SerializerMethodField()
    sessions_per_week = serializers.SerializerMethodField()
    attendance_dates_count = serializers.SerializerMethodField()
    schedule = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    attachments = ClubAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Club
        fields = [
            'id', 'club_name', 'academic_year', 'start_date', 'end_date',
            'plan', 'criteria', 'status', 'member_count', 'sessions_per_week',
            'attendance_dates_count', 'schedule', 'members', 'attachments',
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_member_count(self, obj):
        annotated = getattr(obj, 'member_count_value', None)
        return annotated if annotated is not None else obj.members.count()

    @extend_schema_field(OpenApiTypes.INT)
    def get_sessions_per_week(self, obj):
        return len(self._sessions(obj))

    @extend_schema_field(OpenApiTypes.INT)
    def get_attendance_dates_count(self, obj):
        annotated = getattr(obj, 'attendance_dates_count_value', None)
        if annotated is not None:
            return annotated
        return ClubAttendance.objects.filter(
            session__club=obj,
        ).values('date').distinct().count()

    @extend_schema_field(ClubSessionSerializer(many=True))
    def get_schedule(self, obj):
        return ClubSessionSerializer(self._sessions(obj), many=True).data

    @extend_schema_field(ClubStudentSerializer(many=True))
    def get_members(self, obj):
        if not self.context.get('include_members', False):
            return None
        members = getattr(obj, 'prefetched_club_members', None)
        if members is None:
            members = obj.members.select_related('user').all()
        return ClubStudentSerializer(members, many=True, context=self.context).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get('include_members', False):
            data.pop('members', None)
        return data

    @staticmethod
    def _sessions(obj):
        prefetched = getattr(obj, 'active_club_sessions', None)
        return prefetched if prefetched is not None else list(obj.sessions.all())


class StudentClubSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    club_name = serializers.CharField(source='name')
    academic_year = serializers.CharField(source='academic_year.year', read_only=True)
    total_session_count = serializers.IntegerField(
        source='student_total_session_count', read_only=True,
    )
    present_count = serializers.IntegerField(
        source='student_present_count', read_only=True,
    )
    late_count = serializers.IntegerField(
        source='student_late_count', read_only=True,
    )
    absent_count = serializers.IntegerField(
        source='student_absent_count', read_only=True,
    )

    class Meta:
        model = Club
        fields = [
            'id', 'student', 'academic_year', 'start_date', 'end_date',
            'club_name', 'total_session_count', 'present_count', 'late_count',
            'absent_count', 'created_at',
        ]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_student(self, obj):
        student = self.context['student']
        return {
            'id': student.id,
            'full_name': student.user.get_full_name() or student.user.username,
        }


class StudentClubDetailSerializer(StudentClubSerializer):
    status = serializers.CharField(read_only=True)
    schedule = serializers.SerializerMethodField()

    class Meta(StudentClubSerializer.Meta):
        fields = [
            'id', 'student', 'club_name', 'academic_year', 'status',
            'start_date', 'end_date', 'plan', 'criteria',
            'total_session_count', 'present_count', 'late_count',
            'absent_count', 'created_at', 'schedule',
        ]

    @extend_schema_field(ClubSessionSerializer(many=True))
    def get_schedule(self, obj):
        sessions = getattr(obj, 'active_club_sessions', None)
        if sessions is None:
            sessions = obj.sessions.all()
        return ClubSessionSerializer(sessions, many=True).data


class ClubScheduleWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    weekday = serializers.ChoiceField(choices=ClubSession.WEEKDAY_CHOICES)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    location = serializers.CharField(max_length=255)

    def validate(self, attrs):
        if attrs['end_time'] <= attrs['start_time']:
            raise serializers.ValidationError({
                'end_time': 'End time must be after the start time.'
            })
        return attrs


class ClubWriteSerializer(serializers.Serializer):
    club_name = serializers.CharField(max_length=255)
    academic_year_id = serializers.PrimaryKeyRelatedField(
        source='academic_year', queryset=AcademicYear.objects.all()
    )
    manager_id = serializers.PrimaryKeyRelatedField(
        source='manager', queryset=ClubManager.objects.select_related('user'),
        required=False,
    )
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    plan = serializers.CharField(required=False, allow_blank=True)
    criteria = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Club.CLUB_STATUS_CHOICES, required=False)
    schedule = ClubScheduleWriteSerializer(many=True, required=False)

    def validate(self, attrs):
        instance = self.instance
        start_date = attrs.get('start_date', getattr(instance, 'start_date', None))
        end_date = attrs.get('end_date', getattr(instance, 'end_date', None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({
                'end_date': 'End date must be on or after the start date.'
            })
        if attrs.get('status') == 'deleted':
            raise serializers.ValidationError({
                'status': 'Use the club DELETE endpoint to set deleted status.'
            })

        request = self.context['request']
        user = request.user

        # Club creation is always owned by the ClubManager profile attached to
        # the authenticated user. Never trust a manager ID from the client for
        # this operation.
        if self.instance is None:
            try:
                attrs['manager'] = ClubManager.objects.get(user_id=user.id)
            except ClubManager.DoesNotExist:
                raise serializers.ValidationError({
                    'manager': 'No ClubManager profile exists for the authenticated user.'
                })
        elif not is_admin_role(user) and 'manager' in attrs:
            try:
                own_manager = ClubManager.objects.get(user_id=user.id)
            except ClubManager.DoesNotExist:
                raise serializers.ValidationError({
                    'manager': 'No ClubManager profile exists for the authenticated user.'
                })
            if attrs['manager'] != own_manager:
                raise serializers.ValidationError({
                    'manager_id': 'Club Managers cannot assign clubs to another manager.'
                })

        if 'schedule' in attrs:
            self._validate_schedule(attrs['schedule'])
        return attrs

    @staticmethod
    def _validate_schedule(schedule):
        ids = [row['id'] for row in schedule if 'id' in row]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({'schedule': ['Schedule IDs must be unique.']})

        by_weekday = {}
        for row in schedule:
            by_weekday.setdefault(row['weekday'], []).append(row)
        for weekday, rows in by_weekday.items():
            rows.sort(key=lambda row: row['start_time'])
            for previous, current in zip(rows, rows[1:]):
                if current['start_time'] < previous['end_time']:
                    label = weekday.capitalize()
                    first = (
                        f"{previous['start_time'].strftime('%H:%M')}–"
                        f"{previous['end_time'].strftime('%H:%M')}"
                    )
                    second = (
                        f"{current['start_time'].strftime('%H:%M')}–"
                        f"{current['end_time'].strftime('%H:%M')}"
                    )
                    raise serializers.ValidationError({
                        'schedule': [f'{label} sessions {first} and {second} overlap.']
                    })

    @transaction.atomic
    def create(self, validated_data):
        schedule = validated_data.pop('schedule', [])
        name = validated_data.pop('club_name')
        club = Club.objects.create(name=name, **validated_data)
        ClubSession.objects.bulk_create([
            ClubSession(club=club, **row) for row in schedule
        ])
        return club

    @transaction.atomic
    def update(self, instance, validated_data):
        schedule = validated_data.pop('schedule', serializers.empty)
        if 'club_name' in validated_data:
            instance.name = validated_data.pop('club_name')
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if schedule is not serializers.empty:
            self._replace_schedule(
                instance,
                schedule,
                deleted_by=self.context['request'].user,
            )
        return instance

    @staticmethod
    def _replace_schedule(club, schedule, deleted_by):
        existing = {row.id: row for row in club.sessions.select_for_update()}
        submitted_ids = {row['id'] for row in schedule if 'id' in row}
        unknown = submitted_ids - set(existing)
        if unknown:
            raise serializers.ValidationError({
                'schedule': [f'Unknown schedule IDs for this club: {sorted(unknown)}.']
            })

        now = timezone.now()
        ClubSession.objects.filter(
            club=club,
        ).exclude(id__in=submitted_ids).update(
            is_deleted=True,
            deleted_at=now,
            deleted_by=deleted_by,
        )

        to_create = []
        for row in schedule:
            session_id = row.pop('id', None)
            if session_id is None:
                to_create.append(ClubSession(club=club, **row))
                continue
            session = existing[session_id]
            for field, value in row.items():
                setattr(session, field, value)
            session.save(update_fields=['weekday', 'start_time', 'end_time', 'location'])
        ClubSession.objects.bulk_create(to_create)


class ClubMemberReplaceSerializer(serializers.Serializer):
    student_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=True,
    )

    def validate_student_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError('Student IDs must be unique.')
        found = Student.objects.in_bulk(value)
        missing = sorted(set(value) - set(found))
        if missing:
            raise serializers.ValidationError(f'Unknown student IDs: {missing}.')
        return value


class ClubAttendanceRecordWriteSerializer(serializers.Serializer):
    attendance_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    student_id = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=ClubAttendance.ATTENDANCE_CHOICES)


class ClubAttendanceWriteSerializer(serializers.Serializer):
    records = ClubAttendanceRecordWriteSerializer(many=True, allow_empty=False)

    def validate_records(self, value):
        ids = [row['student_id'] for row in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError('Each student may appear only once.')
        attendance_ids = [
            row['attendance_id'] for row in value if row.get('attendance_id') is not None
        ]
        if len(attendance_ids) != len(set(attendance_ids)):
            raise serializers.ValidationError('Each attendance ID may appear only once.')
        expected_student_ids = self.context.get('expected_student_ids')
        if expected_student_ids is None:
            return value
        expected = set(expected_student_ids)
        if self.context.get('require_complete', True) and set(ids) != expected:
            raise serializers.ValidationError(
                'Attendance must be marked for every current or previously recorded member.'
            )
        if not set(ids).issubset(expected):
            raise serializers.ValidationError(
                'Attendance can only be changed for current or previously recorded members.'
            )
        return value
