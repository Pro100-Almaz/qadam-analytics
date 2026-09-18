import io
import os

import pytest
from PIL import Image
from django.core.cache import cache
from rest_framework.test import APIClient

from core.factories import (
    UserFactory, StudentFactory, TeacherFactory, ParentFactory,
    SupervisorFactory, AdminUserFactory, AcademicYearFactory,
    ClassGroupFactory, SchoolGroupFactory, EnrollmentFactory,
    SubjectFactory, SubjectOfferingFactory, TeachingAssignmentFactory,
    LessonFactory, TopicFactory,
)


@pytest.fixture(autouse=True)
def isolated_test_cache(settings):
    """Keep cache-backed throttles and reset tokens isolated between tests."""
    settings.CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'qadam-pytest-cache',
        },
    }
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _scope_mode_override(settings):
    """Let the suite be run under a stricter mode than the app boots with.

        PYTEST_SCHOOL_SCOPE_MODE=enforce pytest

    Needed because the mode cannot simply be set in the environment yet: under
    'enforce' the import-time querysets in §8 raise during `django.setup()`, so
    the process never reaches a test. Overriding per-test boots at the settings
    default and then tightens, which is the only way to exercise `_default_scope`
    and to see what phases 3-5 still have to fix.

    This is also phase 4's drain tool: run the suite under 'warn' and aggregate
    the ERROR log to get the list of call sites with no scope.
    """
    mode = os.environ.get('PYTEST_SCHOOL_SCOPE_MODE')
    if mode:
        settings.SCHOOL_SCOPE_MODE = mode
    yield


#: The tenant every test runs inside unless it opts out. Matches
#: SchoolFactory's default slug, so factory-built rows and the ambient scope
#: agree instead of straddling two schools.
DEFAULT_TEST_SCHOOL_SLUG = 'test_school'


def _test_touches_the_db(request):
    """Whether this test has database access.

    Checked rather than assumed: `_default_scope` is autouse, and entering a
    scope needs a School row. Forcing every test in the suite through database
    setup to satisfy a fixture most of them never use would be a poor trade —
    and the ones without a DB never run a query, so they have nothing to scope.
    """
    if request.node.get_closest_marker('django_db') is not None:
        return True
    return bool({'db', 'transactional_db'} & set(request.fixturenames))


@pytest.fixture(autouse=True)
def _default_scope(request):
    """Run every test inside school A.

    `apply_school_scope` fails closed: with no active scope it raises under
    'enforce' and logs an ERROR under 'warn'. The suite predates tenancy and
    enters no scope of its own, so without this every one of its ~460 tests
    would fail the moment SCHOOL_SCOPE_MODE moves off 'off' — and a suite that
    is entirely red tells you nothing about which failures are real.

    It scopes to a concrete school rather than `all_schools()` on purpose.
    ALL would keep the suite green by switching the filter off, which is the
    same as not testing it; a real school keeps the filter live, so the
    existing tests exercise the scoped path they will run in production.

    Opt out with `@pytest.mark.no_auto_scope` — isolation tests need to assert
    the fail-closed behaviour, and cross-school tests set their own scope.

    Inert while the mode is 'off'. That is the point: it lands ahead of the
    flip, so phase 4 changes one env var and nothing else.
    """
    if request.node.get_closest_marker('no_auto_scope'):
        yield
        return

    if not _test_touches_the_db(request):
        yield
        return

    # Resolve `db` explicitly: this fixture is autouse and would otherwise be
    # free to run before pytest-django has set the database up. Asking for it
    # by name orders us after it. `db` delegates to `transactional_db` itself
    # when that is in play, so this is safe for both.
    request.getfixturevalue('db')

    from apps.authentication.models import School
    from core.tenancy import school_scope

    school, _ = School.objects.get_or_create(
        slug=DEFAULT_TEST_SCHOOL_SLUG,
        defaults={'name': 'Test School'},
    )
    with school_scope(school):
        yield


@pytest.fixture(autouse=True)
def clear_school_uuid_cache():
    """The School uuid<->pk cache is a module-level dict; the DB is not.

    pytest-django rolls each test back and Postgres reissues the freed pks, so
    a cached entry from an earlier test would map a reused pk to a uuid that no
    longer exists. The post_save receiver covers tests that create a School;
    this covers the ones that only read.
    """
    from apps.authentication.school_cache import clear_school_cache
    clear_school_cache()
    yield
    clear_school_cache()


@pytest.fixture(autouse=True)
def in_memory_media_storage(settings):
    """Keep file uploads out of S3 — and out of the network entirely.

    `STORAGES['default']` is S3Storage unconditionally (settings raises without
    S3_ENDPOINT_URL, so there is no local-disk mode to fall back to). Nothing
    overrode it for tests, so every test that writes a file — club and
    achievement attachments, `user__avatar=SimpleUploadedFile(...)` — was doing
    real HTTP to whatever S3_ENDPOINT_URL pointed at. On a developer machine
    that is a running MinIO, which makes the suite slow, order-dependent and
    quietly full of leftover objects; in CI it is nothing at all, and the tests
    fail on a connection error.

    InMemoryStorage keeps the whole thing in the process and serves URLs under
    MEDIA_URL, so `request.build_absolute_uri()` gives the
    `http://testserver/media/...` the assertions already expect instead of a
    presigned MinIO link. Setting STORAGES fires `setting_changed`, which resets
    Django's `default_storage` lazy object, so FileFields pick this up.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    }
    _seed_default_avatar()
    yield


def _seed_default_avatar():
    """Put the default avatar in the bucket, because the code assumes it is there.

    `CustomUser.avatar` defaults to 'avatars/default/default-user.jpeg' and
    `validate_avatar_size` reads `file.size` on it, which goes to storage. So
    any `full_clean()` of a user — the admin's add form, every ModelForm —
    raises FileNotFoundError if that one object is missing.

    Nothing seeds it: `minio-init` only creates the bucket. It exists on this
    dev machine because somebody uploaded it once, which is also why a fresh
    MinIO in CI would not have fixed these tests. Seeding it here reproduces the
    state the application actually assumes.
    """
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    name = get_user_model()._meta.get_field('avatar').get_default()
    if name and not default_storage.exists(name):
        buffer = io.BytesIO()
        Image.new('RGB', (1, 1)).save(buffer, format='JPEG')
        default_storage.save(name, ContentFile(buffer.getvalue()))


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def academic_year(db):
    return AcademicYearFactory(is_active=True)


@pytest.fixture
def class_group(academic_year):
    return ClassGroupFactory(academic_year=academic_year)


@pytest.fixture
def school_group(db):
    return SchoolGroupFactory()


@pytest.fixture
def admin_user(db):
    return AdminUserFactory()


@pytest.fixture
def teacher(academic_year):
    return TeacherFactory()


@pytest.fixture
def student(academic_year, school_group):
    return StudentFactory(
        school_group=school_group,
        academic_year=academic_year,
    )


@pytest.fixture
def parent(db):
    return ParentFactory()


@pytest.fixture
def supervisor(db):
    return SupervisorFactory()


@pytest.fixture
def authenticated_client(api_client):
    """Authenticate as a user with a real JWT, exercising the real auth path.

    NOT `force_authenticate`. That sets `request._force_auth_user`, which
    `APIView.perform_authentication` honours *instead of* running the
    authentication classes — so `SchoolScopedJWTAuthentication` never runs and
    never enters the school scope. The middleware cannot cover for it either: it
    runs before DRF and sees AnonymousUser on a tokenless request, so it sets
    UNSET. Under 'enforce' every scoped query in the view then raises, and the
    tests fail for a reason that does not exist in production.

    Minting a real token instead means the tests go through the same code a
    browser does — claim included — so the wiring is covered rather than
    bypassed.
    """
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.authentication.school_cache import uuid_for_school_pk

    def _auth(user):
        refresh = RefreshToken.for_user(user)
        if user.school_id:
            refresh['school_uuid'] = uuid_for_school_pk(user.school_id)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        return api_client
    return _auth


@pytest.fixture
def subject(db):
    return SubjectFactory()


@pytest.fixture
def offering(class_group, subject):
    return SubjectOfferingFactory(
        subject=subject,
        class_group=class_group,
    )


@pytest.fixture
def enrollment(student, class_group):
    return EnrollmentFactory(
        student=student,
        class_group=class_group,
    )


@pytest.fixture
def teaching_assignment(teacher, offering):
    return TeachingAssignmentFactory(
        teacher=teacher,
        offering=offering,
    )


@pytest.fixture
def lesson(offering):
    return LessonFactory(offering=offering)


@pytest.fixture
def topics(lesson):
    """Create 3 topics with weights summing to 100."""
    t1 = TopicFactory(lesson=lesson, title='Topic A', weight=40, order=0)
    t2 = TopicFactory(lesson=lesson, title='Topic B', weight=30, order=1)
    t3 = TopicFactory(lesson=lesson, title='Topic C', weight=30, order=2)
    return [t1, t2, t3]
