from datetime import time, timedelta

import factory
from django.contrib.auth.models import Group
from factory.django import DjangoModelFactory

from apps.achievement.models import Club, ClubAttendance, ClubSession
from apps.authentication.models import (
    ClubManager,
    School,
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
    MinorClassGroup,
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


#: The tenant every test runs inside unless it opts out. conftest's autouse
#: `_default_scope` fixture enters this school, and `_current_school()` falls
#: back to it, so factory-built rows and the ambient scope always agree.
DEFAULT_TEST_SCHOOL_SLUG = 'test_school'


class SchoolFactory(DjangoModelFactory):
    """A tenant.

    `django_get_or_create` on the slug means asking twice returns the same row
    rather than a second school. Pass an explicit slug for a second tenant:
    `SchoolFactory(slug='school_b')`.
    """

    class Meta:
        model = School
        django_get_or_create = ('slug',)

    slug = DEFAULT_TEST_SCHOOL_SLUG
    name = factory.LazyAttribute(lambda o: o.slug.replace('_', ' ').title())


def _current_school():
    """The school the surrounding test is scoped to.

    Every factory that owns a `school` column reads this, so **one**
    `school_scope(...)` at the top of a test puts the entire object graph in
    that school — offering, subject, class group, users, at any depth.

    Passing `school=` to the outermost factory instead would reach only that
    one object: its SubFactories each resolve their own school independently,
    fall back to the default, and quietly build a graph whose offering is in
    school B while its subject and class group are in school A. That is the
    exact shape of the bug the isolation tests exist to catch, so a world built
    that way would let them pass while measuring nothing. Reading the ambient
    scope removes the chance to forget a branch.

    Deliberate mismatches are still one keyword away, because an explicit
    argument beats this default — `SubjectOfferingFactory(school=b,
    subject__school=a)` is how you write the negative test.

    Falls back to the default test school when there is no usable scope: a
    `no_auto_scope` test, or `all_schools()`. That is the same row conftest
    enters, so this is a no-op for every test that does not ask for a second
    tenant.
    """
    from core.tenancy import ALL, UNSET, get_active_school

    scope = get_active_school()
    if scope is UNSET or scope is ALL:
        school, _ = School.objects.get_or_create(
            slug=DEFAULT_TEST_SCHOOL_SLUG,
            defaults={'name': 'Test School'},
        )
        return school
    # School.objects is unscoped by design — you cannot scope the tenant root.
    return School.objects.get(pk=scope)


class SchoolGroupFactory(DjangoModelFactory):
    class Meta:
        model = SchoolGroup

    school = factory.LazyFunction(_current_school)
    name = factory.Sequence(lambda n: f'Orda {n}')


class UserFactory(DjangoModelFactory):
    class Meta:
        model = CustomUser

    school = factory.LazyFunction(_current_school)
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
    """Per-school again — `school` defaults to the surrounding scope.

    `django_get_or_create` on (school, year) matches the unique constraint, so
    two factories naming the same year in one school return the same row rather
    than tripping an IntegrityError.
    """

    class Meta:
        model = AcademicYear
        django_get_or_create = ('school', 'year')

    school = factory.LazyFunction(_current_school)
    year = factory.Sequence(lambda n: f'202{n}/202{n + 1}')
    is_active = True
    archived = False


def _active_academic_year(school=None):
    """That school's active year, created if this test has not made one yet.

    Was `AcademicYear.objects.filter(is_active=True).first()`, which silently
    returns `None` when no test fixture happened to create an active year — so
    the Student came out with no year at all and the failure surfaced somewhere
    far away, as a missing enrollment or an empty grade list.

    **`SubFactory(AcademicYearFactory)` is wrong here, and is now wrong loudly.**
    It mints a *new* year per object, so two students in one test used to end up
    in different years. Since years went back to being per-school that is no
    longer merely untidy: `AcademicYearFactory` defaults to `is_active=True`, so
    the second one in a school violates `academicyear_one_active_per_school`.
    Reusing the school's active row is both the correct fixture and the only one
    the constraint permits.

    `_base_manager`, not `objects`: the school is named explicitly here, so the
    lookup must not also be narrowed by whatever scope the test happens to be
    in. `ClassGroupFactory(school=b)` inside `school_scope(a)` is a legitimate
    thing for an isolation test to do, and a scoped lookup would hand it a's
    year.
    """
    school = school or _current_school()
    year = AcademicYear._base_manager.filter(
        school=school, is_active=True,
    ).first()
    if year is not None:
        return year
    return AcademicYearFactory(school=school, is_active=True)


class GradeLevelFactory(DjangoModelFactory):
    class Meta:
        model = GradeLevel

    number = factory.Sequence(lambda n: n + 1)


class ClassGroupFactory(DjangoModelFactory):
    class Meta:
        model = ClassGroup

    school = factory.LazyFunction(_current_school)
    academic_year = factory.LazyAttribute(
        lambda o: _active_academic_year(o.school)
    )
    grade_level = factory.SubFactory(GradeLevelFactory)
    letter = 'A'
    category = ClassGroup.MAJOR_CHOICE


class MinorClassGroupFactory(ClassGroupFactory):
    """A подгруппа — named, and not tied to a grade level by default."""

    class Meta:
        model = MinorClassGroup

    grade_level = None
    letter = factory.Sequence(lambda n: f'Subgroup {n}')
    category = ClassGroup.MINOR_CHOICE


class StudentFactory(DjangoModelFactory):
    class Meta:
        model = Student

    user = factory.SubFactory(StudentUserFactory)
    #: The Orda house follows the student, not the ambient scope. Since §7 a
    #: house from another school is a CrossSchoolWriteError, and a test placing
    #: a student in school B while scoped to A is an ordinary isolation test.
    school_group = factory.LazyAttribute(
        lambda o: SchoolGroupFactory(school=o.user.school)
    )
    academic_year = factory.LazyAttribute(
        lambda o: _active_academic_year(o.user.school)
    )


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
    """`school` is derived from the manager on save, or passed explicitly.

    An explicit `school` has to reach the manager and the year too. Since §7 a
    club whose manager or year sits in another school is a CrossSchoolWriteError
    rather than merely untidy fixture data, and `ClubFactory(school=other)` is
    what an isolation test writes when it wants a club *in* that school — not a
    club stitched across two.
    """

    class Meta:
        model = Club

    manager = factory.LazyAttribute(
        lambda o: ClubManagerFactory(
            user__school=getattr(o, 'school', None) or _current_school()
        )
    )
    academic_year = factory.LazyAttribute(
        lambda o: _active_academic_year(
            getattr(o, 'school', None)
            or (o.manager.user.school if o.manager else None)
        )
    )
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

    school = factory.LazyFunction(_current_school)
    name = factory.Sequence(lambda n: f'Subject {n}')
    status = 'active'
    language_group = 'kaz'


class SubjectOfferingFactory(DjangoModelFactory):
    class Meta:
        model = SubjectOffering

    school = factory.LazyFunction(_current_school)
    subject = factory.SubFactory(SubjectFactory)
    class_group = factory.SubFactory(ClassGroupFactory)
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
    # Follows the offering, as the API does; pass it explicitly for a schedule
    # that has no offering of its own.
    class_group = factory.LazyAttribute(
        lambda o: o.offering.class_group if o.offering else None
    )
    quarter = 1


class ScheduleSessionFactory(DjangoModelFactory):
    class Meta:
        model = ScheduleSession

    schedule = factory.SubFactory(SubjectScheduleFactory)
    weekday = 0
    time_start = time(9, 0)
    time_end = time(9, 45)


class ScheduleAttendanceFactory(DjangoModelFactory):
    class Meta:
        model = ScheduleAttendance

    session = factory.SubFactory(ScheduleSessionFactory)
    student = factory.SubFactory(StudentFactory)
    date = factory.Faker('date_object')
    status = 'present'
