"""Generic tenant-isolation tests — §10 of the multi-school plan.

Six properties, asserted over the model registry rather than by hand per
endpoint. The point is that a model added later fails these until someone
classifies it, instead of quietly joining the 40 already here.

Every test pins `SCHOOL_SCOPE_MODE='enforce'`. They assert what is *not*
visible, and under 'off' the filter is switched off entirely — the suite would
go green while measuring nothing. Inheriting the ambient mode is exactly the
"40 passing isolation tests covering nothing" failure the plan warns about.
"""

import datetime
import re
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import URLPattern, URLResolver, get_resolver

from apps.achievement.models import (
    Achievement,
    Attachment,
    Club,
    ClubAttendance,
    ClubEntry,
    ClubSession,
    ReadingEntry,
)
from apps.authentication.models import (
    ClubManager,
    CustomUser,
    Parent,
    PsychologicalState,
    PsychologicalStateTemplates,
    School,
    SchoolGroup,
    Student,
    Supervisor,
    Teacher,
)
from apps.home.models import (
    AcademicYear,
    ClassGroup,
    ClassGroupCollection,
    Enrollment,
    HomeroomTeacherAssignment,
    MinorClassGroup,
    QuarterGrade,
    QuarterGrader,
    Subject,
    SubjectAssignment,
    SubjectGrade,
    SubjectOffering,
    TeachingAssignment,
)
from apps.lesson.models import (
    Homework,
    HomeworkGrade,
    Lesson,
    MergedLessonComment,
    QuarterGradeSnapshot,
    ScheduleAttendance,
    ScheduleSession,
    SubjectSchedule,
    Topic,
    TopicGrade,
)
from apps.notification.models import Notification
from apps.student_report.models import StudentReport
from core import factories as f
from core.checks import SHARED_MODELS, UNSCOPED_DEFAULT_MANAGER, _tenant_models
from core.tenancy import SchoolScopeError, all_schools, no_school_scope, school_scope

pytestmark = [pytest.mark.django_db, pytest.mark.no_auto_scope]


@pytest.fixture(autouse=True)
def _enforce(settings):
    """Pin the mode for this module.

    A module-level `override_settings` object cannot go in `pytestmark` — it is
    not a pytest Mark. An autouse fixture is the equivalent, and it runs after
    conftest's `_scope_mode_override`, so it wins over PYTEST_SCHOOL_SCOPE_MODE
    too.
    """
    settings.SCHOOL_SCOPE_MODE = 'enforce'


def _scoped_models():
    return [m for m in _tenant_models() if m._meta.label not in SHARED_MODELS]


def _label(model):
    return model._meta.label


def _scoped_manager(model):
    """The manager that is supposed to be scoped.

    For all but one model that is `objects`. `CustomUser.objects` is global on
    purpose — `ModelBackend.authenticate` calls `_default_manager` before
    anyone knows who the user is, so a fail-closed default manager makes login
    itself raise (core.checks.UNSCOPED_DEFAULT_MANAGER). Its scoped manager is
    `in_school`, and that is what the API lists, so that is what these tests
    must assert on. Asserting on `objects` would just re-measure the documented
    exemption and fail.
    """
    if _label(model) in UNSCOPED_DEFAULT_MANAGER:
        return model.in_school
    return model._default_manager


# ── the world builder ───────────────────────────────────────────────────────

def build_world(school, marker):
    """One row of every scoped model, inside `school`.

    `marker` goes into every free-text field so the endpoint sweep can search
    for school B's string in a body served to school A, which covers nested
    serializers and the analytics endpoints where a per-field assertion would
    be unwritable.

    Factories read the ambient scope (`core.factories._current_school`), so the
    whole graph lands in one school from this single `school_scope`. The three
    models whose path could be NULL get a row with that FK *unset* on purpose —
    a school-wide SubjectSchedule, a comment with no lesson, a state with no
    student. Without those the conservation test passes without exercising the
    case it exists for.
    """
    created = {}

    with school_scope(school):
        # Per-school again, so the year is itself one of the scoped models the
        # sweep has to cover — and the marker goes in its name, since the year
        # string is rendered in plenty of serializers.
        year = (
            AcademicYear.objects.filter(is_active=True).first()
            or f.AcademicYearFactory(is_active=True, year=f'20{marker}0/20{marker}1')
        )
        created[AcademicYear] = year

        created[SchoolGroup] = f.SchoolGroupFactory(name=f'Orda {marker}')
        created[CustomUser] = f.UserFactory(
            username=f'plain_{marker}', first_name=f'Person {marker}')

        # People carry the marker in their NAME, not just their pk. A leaked
        # student detail is the highest-value leak on this surface and would
        # otherwise slip past the sweep, whose rule is "the body contains
        # school B's marker" — factory names are random and match nothing.
        student = f.StudentFactory(academic_year=year, user__first_name=f'Pupil {marker}')
        teacher = f.TeacherFactory(user__first_name=f'Tutor {marker}')
        created[Student], created[Teacher] = student, teacher
        created[Parent] = f.ParentFactory(user__first_name=f'Guardian {marker}')
        created[Supervisor] = f.SupervisorFactory(user__first_name=f'Overseer {marker}')
        manager = f.ClubManagerFactory(user__first_name=f'Steward {marker}')
        created[ClubManager] = manager

        class_group = f.ClassGroupFactory(academic_year=year, letter=marker)
        created[ClassGroup] = class_group
        created[MinorClassGroup] = f.MinorClassGroupFactory(academic_year=year, letter=f'm{marker}')
        created[ClassGroupCollection] = ClassGroupCollection.objects.create(major=class_group)
        created[Enrollment] = f.EnrollmentFactory(student=student, class_group=class_group)
        created[HomeroomTeacherAssignment] = HomeroomTeacherAssignment.objects.create(
            teacher=teacher, class_group=class_group)

        subject = f.SubjectFactory(name=f'Subject {marker}')
        created[Subject] = subject
        offering = f.SubjectOfferingFactory(subject=subject, class_group=class_group)
        created[SubjectOffering] = offering
        assignment = f.TeachingAssignmentFactory(offering=offering, teacher=teacher)
        created[TeachingAssignment] = assignment
        created[QuarterGrade] = QuarterGrade.objects.create(
            student=student, offering=offering, quarter=1, grade=80)
        created[QuarterGrader] = QuarterGrader.objects.create(subject=subject, quarter=1)

        subj_assignment = f.SubjectAssignmentFactory(offering=offering)
        created[SubjectAssignment] = subj_assignment
        created[SubjectGrade] = f.SubjectGradeFactory(assignment=subj_assignment, student=student)

        lesson = f.LessonFactory(offering=offering, title=f'Lesson {marker}')
        created[Lesson] = lesson
        topic = f.TopicFactory(lesson=lesson, title=f'Topic {marker}')
        created[Topic] = topic
        created[TopicGrade] = f.TopicGradeFactory(topic=topic, student=student)
        homework = Homework.objects.create(
            offering=offering, teaching_assignment=assignment,
            description=f'Homework {marker}', max_grade=10,
            due_date=datetime.date.today() + datetime.timedelta(days=7))
        created[Homework] = homework
        created[HomeworkGrade] = HomeworkGrade.objects.create(homework=homework, student=student)
        created[QuarterGradeSnapshot] = QuarterGradeSnapshot.objects.create(
            student=student, offering=offering, quarter=1,
            final_grade=Decimal('80.00'), percentage=Decimal('80.00'),
            lesson_count=1, graded_lesson_count=1, frozen_by=teacher.user)

        schedule = f.SubjectScheduleFactory(offering=offering)
        created[SubjectSchedule] = schedule
        session = f.ScheduleSessionFactory(schedule=schedule)
        created[ScheduleSession] = session
        created[ScheduleAttendance] = f.ScheduleAttendanceFactory(session=session, student=student)

        club = f.ClubFactory(manager=manager, academic_year=year, name=f'Club {marker}')
        created[Club] = club
        club_session = f.ClubSessionFactory(club=club)
        created[ClubSession] = club_session
        created[ClubAttendance] = f.ClubAttendanceFactory(session=club_session, student=student)
        created[ClubEntry] = ClubEntry.objects.create(
            student=student, academic_year=year, month=1, club_name=f'Entry {marker}')
        created[ReadingEntry] = ReadingEntry.objects.create(
            student=student, academic_year=year, month=1, title=f'Book {marker}')
        achievement = Achievement.objects.create(
            student=student, academic_year=year, category='olympiad',
            award_type=f'Award {marker}')
        created[Achievement] = achievement
        created[Attachment] = Attachment.objects.create(
            school=school, content_type=ContentType.objects.get_for_model(Achievement),
            object_id=achievement.pk, original_name=f'file_{marker}.pdf',
            file=SimpleUploadedFile(f'{marker}.pdf', b'%PDF-1.4', 'application/pdf'))

        created[PsychologicalStateTemplates] = PsychologicalStateTemplates.objects.create(
            name=f'Template {marker}', school=school)
        created[Notification] = Notification.objects.create(
            user=student.user, type='info', message=f'Note {marker}')
        created[StudentReport] = StudentReport.objects.create(
            student=student, academic_year=year, quarter=1)

        # ── the nullable-path rows: the reason 11 models carry their own
        # school column. Each has its only route to a school left NULL.
        created[MergedLessonComment] = MergedLessonComment.objects.create(
            school=school, comment_text=f'Orphan comment {marker}')
        created[PsychologicalState] = PsychologicalState.objects.create(
            name=f'State {marker}', school=school)
        SubjectSchedule.objects.create(
            school=school, quarter=1,
            description=f'School-wide schedule {marker}')

    return created


@pytest.fixture
def two_worlds():
    a = f.SchoolFactory(slug='iso_school_a', name='Iso School A')
    b = f.SchoolFactory(slug='iso_school_b', name='Iso School B')
    return (a, build_world(a, 'A')), (b, build_world(b, 'B'))


# ── 1. registry completeness ────────────────────────────────────────────────

def test_every_tenant_model_is_scoped_or_explicitly_shared():
    """A new model fails this until someone classifies it."""
    unclassified = [
        _label(m) for m in _tenant_models()
        if getattr(m, 'SCHOOL_PATH', None) is None and _label(m) not in SHARED_MODELS
    ]
    assert not unclassified, (
        f'Models in a tenant app with neither SCHOOL_PATH nor an entry in '
        f'core.checks.SHARED_MODELS: {unclassified}'
    )


def test_build_world_covers_every_scoped_model(two_worlds):
    """Guards the guard.

    Tests 3 and 6 below compare pk sets. A model missing from build_world has
    two EMPTY sets, which are disjoint and do conserve — so it passes while
    covering nothing. This is what stops that.
    """
    (_, world_a), _ = two_worlds
    covered = {m._meta.label for m in world_a}
    missing = sorted({_label(m) for m in _scoped_models()} - covered)
    assert not missing, f'build_world() creates no row for: {missing}'


# ── 2. no nullable link in any SCHOOL_PATH ──────────────────────────────────

@pytest.mark.parametrize('model', _scoped_models(), ids=_label)
def test_no_nullable_link_in_the_school_path(model):
    """The SubjectSchedule class of bug, caught mechanically.

    A filter across a nullable FK becomes an INNER JOIN, so rows whose FK is
    NULL match nothing — for every user, in every school. Such a model must
    carry its own school column instead.
    """
    from core.checks import NULLABLE_LINK_EXEMPTIONS, _walk

    for owner, field in _walk(model, model.SCHOOL_PATH):
        name = f'{owner._meta.label}.{field.name}'
        if field.null and name not in NULLABLE_LINK_EXEMPTIONS:
            pytest.fail(
                f'{_label(model)}.SCHOOL_PATH crosses nullable {name}. Rows '
                f'with it NULL would be invisible to every school; give '
                f'{_label(model)} its own school FK instead.'
            )


# ── 3. model isolation ──────────────────────────────────────────────────────

@pytest.mark.parametrize('model', _scoped_models(), ids=_label)
def test_each_school_sees_only_its_own_rows(model, two_worlds):
    (school_a, _), (school_b, _) = two_worlds

    manager = _scoped_manager(model)
    with school_scope(school_a):
        seen_a = set(manager.values_list('pk', flat=True))
    with school_scope(school_b):
        seen_b = set(manager.values_list('pk', flat=True))

    # Both non-empty, or the disjointness below is vacuous.
    assert seen_a, f'{_label(model)}: school A sees nothing — build_world gap?'
    assert seen_b, f'{_label(model)}: school B sees nothing — build_world gap?'
    assert not (seen_a & seen_b), (
        f'{_label(model)}: rows visible to BOTH schools: {sorted(seen_a & seen_b)}'
    )


# ── 4. endpoint sweep ───────────────────────────────────────────────────────

_INT_CAPTURE = re.compile(r'<int:(\w+)>')
#: any capture at all — `path()` converters and `re_path()` groups alike
_ANY_CAPTURE = re.compile(r'<[^>]+>|\(\?P<\w+>')


def _api_routes():
    """Every route under /api/, as (full route string, list of int captures).

    `str(URLPattern.pattern)` is the *route* for `path()` — `subjects/<int:pk>/`
    — and a regex only for `re_path()`. An earlier version of this matched
    `(?P<...>` only, collected zero routes, and passed vacuously.
    """
    routes = []

    def walk(patterns, prefix=''):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                full = prefix + str(p.pattern)
                if full.startswith('api/'):
                    routes.append(full)

    walk(get_resolver().url_patterns)
    return routes


def _int_pk_detail_routes():
    """Detail routes whose ONLY capture is an int pk — the bare APIView shape."""
    out = []
    for full in _api_routes():
        ints = _INT_CAPTURE.findall(full)
        if len(ints) == 1 and len(_ANY_CAPTURE.findall(full)) == 1:
            out.append((full, ints[0]))
    return out


def _no_argument_list_routes():
    return [full for full in _api_routes() if not _ANY_CAPTURE.search(full)]


#: Every free-text field in build_world ends with the marker, so a body
#: carrying school B's data carries one of these. Matching on the marker rather
#: than on the status code is what makes the sweep precise: a 200 is not itself
#: proof of a leak — school A may own a row with the same pk in a different
#: table, and `<int:pk>` routes give no way to know which model a pk belongs to.
def _marker_needles(marker):
    return (
        f'Subject {marker}', f'Club {marker}', f'Orda {marker}',
        f'Lesson {marker}', f'Topic {marker}', f'Book {marker}',
        f'Award {marker}', f'State {marker}', f'Template {marker}',
        f'Entry {marker}', f'Note {marker}', f'Homework {marker}',
        f'Orphan comment {marker}', f'School-wide schedule {marker}',
        f'Person {marker}', f'Pupil {marker}', f'Tutor {marker}',
        f'Guardian {marker}', f'Overseer {marker}', f'Steward {marker}',
    )


def _leaked_needles(body, marker):
    return [n for n in _marker_needles(marker) if n in body]


def _admin_client(api_client, school, username):
    from rest_framework_simplejwt.tokens import RefreshToken

    with school_scope(school):
        admin = f.AdminUserFactory(username=username)
    token = RefreshToken.for_user(admin)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return api_client


def test_a_school_a_admin_never_receives_school_bs_data_by_pk(two_worlds, api_client):
    """Walk every int-pk detail route with school B's pks."""
    (school_a, _), (_, world_b) = two_worlds
    client = _admin_client(api_client, school_a, 'iso_admin_a')

    routes = _int_pk_detail_routes()
    assert len(routes) > 20, (
        f'only {len(routes)} int-pk detail routes collected — the sweep is not '
        f'walking the URLconf, so it would pass vacuously'
    )

    b_pks = sorted({obj.pk for obj in world_b.values() if isinstance(obj.pk, int)})
    probed, leaked = 0, []
    for pattern, capture in routes:
        for pk in b_pks:
            url = '/' + pattern.replace(f'<int:{capture}>', str(pk))
            try:
                resp = client.get(url)
            except Exception:
                continue        # a raising view is not a leak; test 5 covers those
            probed += 1
            if resp.status_code != 200:
                continue
            hits = _leaked_needles(resp.content.decode('utf-8', 'replace'), 'B')
            if hits:
                leaked.append((url, hits))

    assert probed > 100, f'only {probed} requests made — the sweep is too thin'
    assert not leaked, (
        f"school B's data reached a school-A admin on {len(leaked)} url(s): "
        f'{leaked[:10]}'
    )


def test_school_bs_marker_never_appears_in_a_list_served_to_school_a(two_worlds, api_client):
    """Generic enough to cover nested serializers and the analytics endpoints."""
    (school_a, _), _ = two_worlds
    client = _admin_client(api_client, school_a, 'iso_admin_a2')

    list_urls = ['/' + r for r in _no_argument_list_routes()]
    assert len(list_urls) > 10, (
        f'only {len(list_urls)} no-argument list routes collected — the sweep '
        f'is not walking the URLconf'
    )

    offenders = []
    for url in list_urls:
        try:
            resp = client.get(url)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        hits = _leaked_needles(resp.content.decode('utf-8', 'replace'), 'B')
        if hits:
            offenders.append((url, hits))

    assert not offenders, (
        f"school B's rows appeared in a body served to school A: {offenders}"
    )


# ── 5. fail-closed smoke ────────────────────────────────────────────────────

@pytest.mark.parametrize('model', _scoped_models(), ids=_label)
def test_querying_with_no_scope_raises(model):
    manager = _scoped_manager(model)
    with no_school_scope():
        with pytest.raises(SchoolScopeError):
            list(manager.all()[:1])


# ── 6. conservation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('model', _scoped_models(), ids=_label)
def test_every_row_is_visible_to_exactly_one_school(model, two_worlds):
    """The direct guard against the nullable-path failure."""
    manager = _scoped_manager(model)
    with all_schools():
        everything = set(manager.values_list('pk', flat=True))

    seen, doubled = set(), set()
    with all_schools():
        schools = list(School.objects.all())
    for school in schools:
        with school_scope(school):
            visible = set(manager.values_list('pk', flat=True))
        doubled |= seen & visible
        seen |= visible

    assert not (everything - seen), (
        f'{_label(model)}: rows visible to NO school: {sorted(everything - seen)[:10]}. '
        f'Its SCHOOL_PATH probably crosses a nullable FK — give it its own '
        f'school column.'
    )
    assert not doubled, f'{_label(model)}: rows visible to two schools: {sorted(doubled)[:10]}'
