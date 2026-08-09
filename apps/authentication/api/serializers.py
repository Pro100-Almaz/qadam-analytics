from django.contrib.auth import authenticate
from django.contrib.auth.models import Group
from django.db import transaction
from rest_framework import serializers

from apps.authentication.models import (
    CustomUser, Student, Teacher, Parent, Supervisor, ClubManager,
    SchoolGroup, PsychologicalState, PsychologicalStateTemplates,
    MAX_AVATAR_SIZE_MB, MAX_AVATAR_SIZE_BYTES,
)


class PublicSchoolGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolGroup
        fields = ['id', 'name']


class SchoolGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolGroup
        fields = ['id', 'name', 'avatar', 'color']


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    primary_group = serializers.CharField(read_only=True)
    profile_id = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone_number', 'date_of_birth', 'address', 'avatar',
            'school', 'roles', 'role_display', 'primary_group', 'profile_id',
        ]
        read_only_fields = ['id', 'username']

    def get_profile_id(self, obj):
        for attr in ('student', 'teacher', 'parent', 'supervisor', 'clubmanager'):
            profile = getattr(obj, attr, None)
            if profile is not None:
                return profile.pk
        return None

    def get_avatar(self, obj):
        request = self.context.get('request')
        if request and obj.avatar:
            return request.build_absolute_uri(obj.avatar.url)
        return None

    def get_roles(self, obj):
        groups = [group.name.lower() for group in obj.groups.all()]
        for i in range(len(groups)):
            groups[i] = groups[i].replace('homeroomteacher', 'homeroom_teacher')
        return groups


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'email', 'first_name', 'last_name',
            'phone_number', 'date_of_birth', 'address',
        ]

    def validate_email(self, value):
        user = self.instance
        if CustomUser.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Адрес электронной почты уже зарегистрирован")
        return value


class AvatarUploadSerializer(serializers.Serializer):
    avatar = serializers.ImageField()

    def validate_avatar(self, value):
        if value.size > MAX_AVATAR_SIZE_BYTES:
            raise serializers.ValidationError(
                f'Avatar file size must be less than {MAX_AVATAR_SIZE_MB}MB. '
                f'Current size: {value.size / (1024 * 1024):.2f}MB'
            )
        return value


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        username = attrs['username']
        password = attrs['password']

        user = authenticate(username=username, password=password)
        if user:
            attrs['user'] = user
            return attrs

        if not CustomUser.objects.filter(username=username).exists():
            raise serializers.ValidationError({"username": "Логин не совпадает"})
        raise serializers.ValidationError({"password": "Пароль не совпадает"})


class RegisterSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    school = serializers.ChoiceField(choices=CustomUser.SCHOOL_CHOICES, required=False)
    role = serializers.ChoiceField(choices=CustomUser.GROUP_CHOICES)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    address = serializers.CharField(required=False, allow_blank=True)
    avatar = serializers.ImageField(required=False)

    # Teacher-specific
    gender = serializers.ChoiceField(choices=Teacher.GENDER_CHOICES, required=False)
    academic_degree = serializers.CharField(required=False, allow_blank=True)
    employment_type = serializers.ChoiceField(
        choices=Teacher.EMPLOYMENT_TYPE_CHOICES, required=False
    )
    occupation = serializers.CharField(required=False, allow_blank=True)

    # Student-specific
    school_group = serializers.PrimaryKeyRelatedField(
        queryset=SchoolGroup.objects.all(), required=False, allow_null=True
    )
    medical_features = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    # Parent-specific
    student_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs['password1'] != attrs['password2']:
            raise serializers.ValidationError({"password2": "Пароль не совпадает"})

        if CustomUser.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError(
                {"email": "Адрес электронной почты уже зарегистрирован"}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        group_name = validated_data.pop('role')
        password = validated_data.pop('password1')
        validated_data.pop('password2')

        avatar = validated_data.pop('avatar', None)
        gender = validated_data.pop('gender', None)
        academic_degree = validated_data.pop('academic_degree', None)
        employment_type = validated_data.pop('employment_type', None)
        occupation = validated_data.pop('occupation', None)
        school_group = validated_data.pop('school_group', None)
        medical_features = validated_data.pop('medical_features', None)
        student_id = validated_data.pop('student_id', None)

        user = CustomUser(
            username=validated_data['email'],
            **validated_data,
        )
        user.set_password(password)
        user.save()

        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

        if avatar:
            user.avatar = avatar
            user.save(update_fields=['avatar'])

        if group_name in (CustomUser.GROUP_TEACHER, CustomUser.GROUP_HOMEROOM_TEACHER):
            Teacher.objects.create(
                user=user,
                gender=gender,
                academic_degree=academic_degree,
                employment_type=employment_type,
                occupation=occupation,
            )
        elif group_name == CustomUser.GROUP_STUDENT:
            Student.objects.create(
                user=user,
                school_group=school_group,
                medical_features=medical_features,
            )
        elif group_name == CustomUser.GROUP_PARENT:
            parent = Parent.objects.create(user=user)
            if student_id:
                try:
                    student = Student.objects.get(pk=student_id)
                    parent.students.add(student)
                except Student.DoesNotExist:
                    pass
        elif group_name in (CustomUser.GROUP_SUPERVISOR, CustomUser.GROUP_PRINCIPAL):
            Supervisor.objects.create(user=user)
        elif group_name == CustomUser.GROUP_CLUB_MANAGER:
            ClubManager.objects.create(user=user)

        return user


class ForgetPasswordSerializer(serializers.Serializer):
    username = serializers.CharField()


class VerificationCodeSerializer(serializers.Serializer):
    username = serializers.CharField()
    verification_code = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    token = serializers.CharField()
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['password1'] != attrs['password2']:
            raise serializers.ValidationError({"password2": "Пароли не совпадают."})
        return attrs


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Пароли не совпадают"})
        return attrs


class StudentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Student
        fields = ['id', 'user', 'school_group', 'academic_year']


class TeacherProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Teacher
        fields = [
            'id', 'user', 'gender', 'academic_degree',
            'employment_type', 'occupation', 'working_hours',
        ]


class ParentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    students = StudentProfileSerializer(many=True, read_only=True)

    class Meta:
        model = Parent
        fields = ['id', 'user', 'students']


class PsychologicalStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologicalState
        fields = ['id', 'name', 'comment', 'student', 'score', 'added_by', 'time_added']
        read_only_fields = ['id', 'added_by', 'time_added']


class PsychologicalStateTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologicalStateTemplates
        fields = ['id', 'name', 'comment']
