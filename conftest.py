import io

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
    """Returns a function that authenticates the client as a given user."""
    def _auth(user):
        api_client.force_authenticate(user=user)
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
