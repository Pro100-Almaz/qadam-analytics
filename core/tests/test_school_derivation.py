"""SchoolDerivedMixin must always land on a school, including for superusers.

The eleven models that carry their own `school` column do so because their path
to a tenant can be NULL. The column is NOT NULL, so a derivation that comes back
empty is not a subtle isolation bug — it is an IntegrityError, a 500 on a routed
endpoint. Two of the declared sources could return nothing:

* `Attachment` derived only from `uploaded_by`, which is SET_NULL and is NULL-
  school for every superuser. Every superuser upload through the club,
  achievement or homework endpoints was a 500.
* `PsychologicalState` derives from `student__user` then `added_by`; a note with
  no student, added by a superuser, satisfies neither.

The first is fixed by deriving from `content_object` — the row the attachment
actually belongs to, which always exists and always reaches a school. The second
has no other anchor, so it must fail loudly and say what to pass.
"""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.achievement.models import Attachment
from apps.authentication.models import PsychologicalState
from core.factories import (
    AdminUserFactory, ClubFactory, SchoolFactory, StudentFactory,
    StudentUserFactory, UserFactory,
)
from core.models import school_id_of
from core.tenancy import SchoolDerivationError


@pytest.fixture
def school(db):
    return SchoolFactory(slug='school_a')


@pytest.fixture
def superuser(db):
    """A superuser has no school by design — that is the whole hole."""
    user = UserFactory(school=None, is_superuser=True, is_staff=True)
    assert user.school_id is None
    return user


def _pdf():
    return SimpleUploadedFile('plan.pdf', b'%PDF-1.4\nplan', 'application/pdf')


def _attach(target, uploaded_by):
    return Attachment.objects.create(
        content_type=ContentType.objects.get_for_model(target),
        object_id=target.pk,
        file=_pdf(),
        file_type='document',
        original_name='plan.pdf',
        uploaded_by=uploaded_by,
    )


@pytest.mark.django_db
def test_superuser_upload_lands_in_the_targets_school(school, superuser):
    """The regression: this raised IntegrityError before content_object was a source."""
    club = ClubFactory(academic_year__school=school)

    attachment = _attach(club, superuser)

    assert attachment.school_id == school.pk


@pytest.mark.django_db
def test_attachment_follows_the_target_not_the_uploader(school):
    """A cross-school upload files under the row's school, not the actor's."""
    other = SchoolFactory(slug='school_b')
    club = ClubFactory(academic_year__school=school)
    uploader = AdminUserFactory(school=other)

    attachment = _attach(club, uploader)

    assert attachment.school_id == school.pk


@pytest.mark.django_db
def test_uploader_is_the_fallback_when_the_target_is_gone(school):
    """content_object resolves to None for a dangling object_id."""
    uploader = AdminUserFactory(school=school)

    attachment = Attachment.objects.create(
        content_type=ContentType.objects.get_for_model(uploader),
        object_id=9_999_999,
        file=_pdf(),
        file_type='document',
        original_name='plan.pdf',
        uploaded_by=uploader,
    )

    assert attachment.school_id == school.pk


@pytest.mark.django_db
def test_school_id_of_walks_the_targets_own_school_path(school):
    """Club has no `school` column — it is scoped by academic_year__school.

    Only looking for a `school_id` attribute is what made the Attachment
    derivation fall through to the uploader in the first place.
    """
    club = ClubFactory(academic_year__school=school)

    assert not hasattr(club, 'school_id')
    assert school_id_of(club) == school.pk


@pytest.mark.django_db
def test_psychological_state_derives_from_the_student(school, superuser):
    """The live path always passes a student, so the superuser case is covered."""
    student = StudentFactory(user=StudentUserFactory(school=school))

    state = PsychologicalState.objects.create(
        name='Сосредоточен', score=4, student=student, added_by=superuser,
    )

    assert state.school_id == school.pk


@pytest.mark.django_db
def test_schoolless_state_by_a_superuser_says_what_to_pass(superuser):
    """No student and no actor school: nothing to derive from, so say so.

    The alternative is a bare NOT NULL IntegrityError naming only the column.
    """
    with pytest.raises(SchoolDerivationError, match='school=... explicitly'):
        PsychologicalState.objects.create(
            name='Общее наблюдение', score=3, student=None, added_by=superuser,
        )


@pytest.mark.django_db
def test_an_explicit_school_is_always_enough(school, superuser):
    """The documented escape hatch for the school-wide case."""
    state = PsychologicalState.objects.create(
        name='Общее наблюдение', score=3, student=None,
        added_by=superuser, school=school,
    )

    assert state.school_id == school.pk
