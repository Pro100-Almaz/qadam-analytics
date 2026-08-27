from datetime import timedelta

import factory
from django.contrib.auth.models import Group
from factory.django import DjangoModelFactory

from apps.achievement.models import Club, ClubAttendance, ClubSession
from apps.authentication.models import (
    ClubManager,
    CustomUser,
    Parent,
    SchoolGroup,
    Student,
    Supervisor,
    Teacher,
)
from apps.home.models import (
    AcademicYear,
    ClassGroup,
    Enrollment,
    GradeLevel,
    Subject,
    SubjectAssignment,
    SubjectGrade,
    SubjectOffering,
    TeachingAssignment,
)
from apps.lesson.models import (
    Lesson,
    ScheduleAttendance,
    ScheduleSession,
    SubjectSchedule,
    Topic,
    TopicGrade,
)


class GroupFactory(DjangoModelFactory):
    class Meta:
        model = Group
        django_get_or_create = ('name',)

    name = 'Student'


class SchoolGroupFactory(DjangoModelFactory):
    class Meta:
        model = SchoolGroup

    name = factory.Sequence(lambda n: f'School {n}')


class UserFactory(DjangoModelFactory):
    class Meta:
        model = CustomUser

    username = factory.Sequence(lambda n: f'user_{n}')
    email = factory.LazyAttribute(lambda o: f'{o.username}@test.kz')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    password = factory.PostGenerationMethodCall('set_password', 'testpass123')

    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            group, _ = Group.objects.get_or_create(name=extracted)
            self.groups.add(group)


class StudentUserFactory(UserFactory):
    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_STUDENT)
        self.groups.add(group)


class TeacherUserFactory(UserFactory):
    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_TEACHER)
        self.groups.add(group)


class AdminUserFactory(UserFactory):
    is_staff = True

    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_ADMIN)
        self.groups.add(group)


class SupervisorUserFactory(UserFactory):
    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_SUPERVISOR)
        self.groups.add(group)


class ParentUserFactory(UserFactory):
    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_PARENT)
        self.groups.add(group)


class ClubManagerUserFactory(UserFactory):
    @factory.post_generation
    def group_name(self, create, extracted, **kwargs):
        if not create:
            return
        group, _ = Group.objects.get_or_create(name=CustomUser.GROUP_CLUB_MANAGER)
        self.groups.add(group)


class AcademicYearFactory(DjangoModelFactory):
    class Meta:
        model = AcademicYear

    year = factory.Sequence(lambda n: f'202{n}/202{n + 1}')
    is_active = True
    archived = False


class GradeLevelFactory(DjangoModelFactory):
    class Meta:
        model = GradeLevel

    number = factory.Sequence(lambda n: n + 1)


class ClassGroupFactory(DjangoModelFactory):
    class Meta:
        model = ClassGroup

    academic_year = factory.SubFactory(AcademicYearFactory)
    grade_level = factory.SubFactory(GradeLevelFactory)
    letter = 'A'


class StudentFactory(DjangoModelFactory):
    class Meta:
        model = Student

    user = factory.SubFactory(StudentUserFactory)
    school_group = factory.SubFactory(SchoolGroupFactory)
    academic_year = factory.LazyAttribute(lambda o: AcademicYear.objects.filter(is_active=True).first())


class TeacherFactory(DjangoModelFactory):
    class Meta:
        model = Teacher

    user = factory.SubFactory(TeacherUserFactory)
    gender = 'male'
    employment_type = 'full_time'


class ParentFactory(DjangoModelFactory):
    class Meta:
        model = Parent

    user = factory.SubFactory(ParentUserFactory)


class SupervisorFactory(DjangoModelFactory):
    class Meta:
        model = Supervisor

    user = factory.SubFactory(SupervisorUserFactory)


class ClubManagerFactory(DjangoModelFactory):
    class Meta:
        model = ClubManager

    user = factory.SubFactory(ClubManagerUserFactory)


class ClubFactory(DjangoModelFactory):
    class Meta:
        model = Club

    manager = factory.SubFactory(ClubManagerFactory)
    academic_year = factory.SubFactory(AcademicYearFactory)
    start_date = factory.Faker('date_object')
    end_date = factory.LazyAttribute(
        lambda obj: obj.start_date + timedelta(days=240)
    )
    name = factory.Sequence(lambda n: f'Club {n}')


class ClubSessionFactory(DjangoModelFactory):
    class Meta:
        model = ClubSession

    club = factory.SubFactory(ClubFactory)
    weekday = 'monday'
    start_time = '15:30'
    end_time = '16:30'
    location = 'Room 204'


class ClubAttendanceFactory(DjangoModelFactory):
    class Meta:
        model = ClubAttendance

    session = factory.SubFactory(ClubSessionFactory)
    student = factory.SubFactory(StudentFactory)
    date = factory.Faker('date_object')
    status = 'present'


class SubjectFactory(DjangoModelFactory):
    class Meta:
        model = Subject

    name = factory.Sequence(lambda n: f'Subject {n}')
    status = 'active'
    language_group = 'kaz'


class SubjectOfferingFactory(DjangoModelFactory):
    class Meta:
        model = SubjectOffering

    subject = factory.SubFactory(SubjectFactory)
    class_group = factory.SubFactory(ClassGroupFactory)
    academic_year = factory.LazyAttribute(lambda o: o.class_group.academic_year)
    max_points = 100
    grading_strategy = 'average'


class TeachingAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = TeachingAssignment

    offering = factory.SubFactory(SubjectOfferingFactory)
    teacher = factory.SubFactory(TeacherFactory)
    role = 'primary'


class EnrollmentFactory(DjangoModelFactory):
    class Meta:
        model = Enrollment

    student = factory.SubFactory(StudentFactory)
    class_group = factory.SubFactory(ClassGroupFactory)
    academic_year = factory.LazyAttribute(lambda o: o.class_group.academic_year)
    status = 'active'


class LessonFactory(DjangoModelFactory):
    class Meta:
        model = Lesson

    offering = factory.SubFactory(SubjectOfferingFactory)
    title = factory.Sequence(lambda n: f'Lesson {n}')
    quarter = 1
    unit = 1
    status = 'pending'
    order = factory.Sequence(lambda n: n)


class TopicFactory(DjangoModelFactory):
    class Meta:
        model = Topic

    lesson = factory.SubFactory(LessonFactory)
    title = factory.Sequence(lambda n: f'Topic {n}')
    weight = 100
    order = factory.Sequence(lambda n: n)


class SubtopicFactory(TopicFactory):
    parent = factory.SubFactory(TopicFactory)
    weight = 50


class TopicGradeFactory(DjangoModelFactory):
    class Meta:
        model = TopicGrade

    topic = factory.SubFactory(TopicFactory)
    student = factory.SubFactory(StudentFactory)
    grade = 0


class SubjectAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = SubjectAssignment

    offering = factory.SubFactory(SubjectOfferingFactory)
    title = factory.Sequence(lambda n: f'Assignment {n}')
    max_grade = 100
    category = 'lesson'
    date = factory.Faker('date_object')


class SubjectGradeFactory(DjangoModelFactory):
    class Meta:
        model = SubjectGrade

    assignment = factory.SubFactory(SubjectAssignmentFactory)
    student = factory.SubFactory(StudentFactory)
    grade = None


class SubjectScheduleFactory(DjangoModelFactory):
    class Meta:
        model = SubjectSchedule

    offering = factory.SubFactory(SubjectOfferingFactory)
    quarter = 1


class ScheduleSessionFactory(DjangoModelFactory):
    class Meta:
        model = ScheduleSession

    schedule = factory.SubFactory(SubjectScheduleFactory)
    order = 1
    weekday = 0


class ScheduleAttendanceFactory(DjangoModelFactory):
    class Meta:
        model = ScheduleAttendance

    session = factory.SubFactory(ScheduleSessionFactory)
    student = factory.SubFactory(StudentFactory)
    date = factory.Faker('date_object')
    status = 'present'
