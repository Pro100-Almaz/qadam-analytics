"""The certificate download endpoint must not assume a local filesystem.

Media storage is S3/MinIO with no local-disk mode, so `FileField.path` raises
NotImplementedError ("This backend doesn't support absolute paths") — the view
500'd on every call, and the `os.path.exists` guard below it never ran. These
tests go through the storage backend, which is what the fix does.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.fields.files import FieldFile
from django.urls import reverse
from rest_framework import status

from apps.achievement.models import Achievement
from core.factories import StudentFactory

pytestmark = pytest.mark.django_db

CERTIFICATE_BYTES = b'%PDF-1.4\nmock certificate'


@pytest.fixture
def achievement(student, academic_year):
    return Achievement.objects.create(
        student=student,
        academic_year=academic_year,
        category='olympiad',
        award_type='Gold Medal',
        certificate=SimpleUploadedFile(
            'diploma.pdf', CERTIFICATE_BYTES, 'application/pdf'
        ),
    )


def _download_url(achievement):
    return reverse(
        'achievement-api:achievement-download', kwargs={'pk': achievement.pk}
    )


def test_download_streams_the_certificate(
    authenticated_client, admin_user, achievement
):
    response = authenticated_client(admin_user).get(_download_url(achievement))

    assert response.status_code == status.HTTP_200_OK
    assert b''.join(response.streaming_content) == CERTIFICATE_BYTES
    assert response['Content-Type'] == 'application/pdf'
    assert 'attachment' in response['Content-Disposition']
    assert 'diploma' in response['Content-Disposition']


def test_download_404s_when_the_stored_object_is_gone(
    authenticated_client, admin_user, achievement
):
    """A row pointing at a deleted object is a 404, not a 500."""
    achievement.certificate.storage.delete(achievement.certificate.name)

    response = authenticated_client(admin_user).get(_download_url(achievement))

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_download_404s_without_a_certificate(
    authenticated_client, admin_user, student, academic_year
):
    bare = Achievement.objects.create(
        student=student,
        academic_year=academic_year,
        category='project',
    )

    response = authenticated_client(admin_user).get(_download_url(bare))

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_download_is_denied_to_an_unrelated_student(
    authenticated_client, achievement, academic_year
):
    outsider = StudentFactory()

    response = authenticated_client(outsider.user).get(_download_url(achievement))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_download_does_not_touch_a_local_path(
    authenticated_client, admin_user, achievement, monkeypatch
):
    """Make `FieldFile.path` behave the way it does on S3 and re-run the download.

    This is why no test caught the bug: the suite swaps media for
    `InMemoryStorage`, whose `path()` cheerfully joins a path and returns one,
    while the S3 backend the app actually runs on raises. With `.path` raising,
    the old view 500'd here.
    """
    def no_absolute_paths(self):
        raise NotImplementedError("This backend doesn't support absolute paths.")

    monkeypatch.setattr(FieldFile, 'path', property(no_absolute_paths))

    response = authenticated_client(admin_user).get(_download_url(achievement))

    assert response.status_code == status.HTTP_200_OK
    assert b''.join(response.streaming_content) == CERTIFICATE_BYTES
