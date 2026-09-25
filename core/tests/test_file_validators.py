"""A missing storage object must not break an unrelated save.

The bug this pins: `full_clean()` runs a FileField's validators on every save,
not only when the file changes. `validate_avatar_size` read `file.size`, which
on S3 storage is a HeadObject — so a row whose avatar object was gone returned
a 500 from the admin change form, on a save that never touched the avatar:

    POST /admin/authentication/customuser/1/change/ -> 500
    FileNotFoundError: File does not exist: media/avatars/2026/01/29/...jpg

These tests use the autouse InMemoryStorage from conftest, which raises the
same FileNotFoundError for a missing name as the S3 backend does.
"""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.achievement.models import (
    MAX_ATTACHMENT_SIZE_BYTES,
    validate_attachment_format,
    validate_attachment_size,
)
from apps.authentication.models import MAX_AVATAR_SIZE_BYTES, validate_avatar_size
from core.factories import UserFactory
from core.validators import is_stored_file

MISSING = 'avatars/2026/01/29/student_example.jpg'


@pytest.mark.django_db
def test_the_storage_object_really_is_missing():
    """Guard the guard: if this stops raising, the tests below prove nothing."""
    user = UserFactory(avatar=MISSING)
    with pytest.raises(FileNotFoundError):
        user.avatar.storage.size(user.avatar.name)


@pytest.mark.django_db
def test_saving_a_user_whose_avatar_object_is_gone_does_not_explode():
    """The reported 500, at the layer the admin actually hits."""
    user = UserFactory(avatar=MISSING)
    user.first_name = 'Renamed'
    user.full_clean(exclude=['password'])      # raised FileNotFoundError before
    user.save()
    assert user.avatar.name == MISSING          # and the reference is untouched


@pytest.mark.django_db
def test_a_stored_avatar_is_not_re_measured():
    user = UserFactory(avatar=MISSING)
    assert is_stored_file(user.avatar)
    assert validate_avatar_size(user.avatar) is None


def test_an_oversized_upload_is_still_rejected():
    upload = SimpleUploadedFile(
        'big.jpg', b'x' * (MAX_AVATAR_SIZE_BYTES + 1), content_type='image/jpeg')
    assert not is_stored_file(upload)
    with pytest.raises(ValidationError, match='must be less than'):
        validate_avatar_size(upload)


def test_an_upload_within_the_limit_passes():
    upload = SimpleUploadedFile('ok.jpg', b'x' * 1024, content_type='image/jpeg')
    assert validate_avatar_size(upload) is None


def test_an_oversized_attachment_upload_is_still_rejected():
    upload = SimpleUploadedFile(
        'big.pdf', b'x' * (MAX_ATTACHMENT_SIZE_BYTES + 1), content_type='application/pdf')
    with pytest.raises(ValidationError, match='must not exceed'):
        validate_attachment_size(upload)


def test_an_attachment_in_a_rejected_format_is_still_rejected():
    upload = SimpleUploadedFile('payload.exe', b'MZ', content_type='application/octet-stream')
    with pytest.raises(ValidationError, match='Unsupported file format'):
        validate_attachment_format(upload)


@pytest.mark.django_db
def test_a_stored_attachment_is_not_reopened():
    """`validate_attachment_format` used to seek() the file — a GetObject."""
    from apps.achievement.models import Attachment

    stored = Attachment._meta.get_field('file').attr_class(
        Attachment(), Attachment._meta.get_field('file'), 'attachments/gone.pdf')
    assert is_stored_file(stored)
    assert validate_attachment_size(stored) is None
    assert validate_attachment_format(stored) is None
