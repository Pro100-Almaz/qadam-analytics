from rest_framework import serializers

from apps.achievement.models import Achievement, ClubEntry, ReadingEntry
from apps.authentication.models import Student
from apps.home.models import AcademicYear, Subject


# ── Shared nested serializers ──

class _StudentBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


# ── Achievement serializers ──

class AchievementListSerializer(serializers.ModelSerializer):
    student = _StudentBriefSerializer(read_only=True)
    academic_year = serializers.StringRelatedField(read_only=True)
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = Achievement
        fields = [
            'id', 'student', 'academic_year', 'category',
            'subject_name', 'award_type', 'place',
            'role', 'duration', 'description',
            'certificate', 'created_at', 'updated_at',
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

    class Meta:
        model = ReadingEntry
        fields = [
            'id', 'student', 'academic_year',
            'title', 'cover', 'month', 'pages_read', 'test_score',
            'created_at',
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

    class Meta:
        model = ClubEntry
        fields = [
            'id', 'student', 'academic_year', 'month',
            'club_name', 'plan', 'criteria',
            'total_sessions', 'attended_sessions', 'comments',
            'created_at',
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
