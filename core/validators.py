"""Helpers shared by the file-field validators.

Django runs a field's validators inside ``full_clean()``, which every
``ModelForm`` — and therefore every admin save — calls whether or not the file
was touched. A validator that reads the file has to tell the two cases apart.
See :func:`is_stored_file`.
"""


def is_stored_file(file):
    """True when `file` is already in storage rather than an incoming upload.

    Django's ``FileDescriptor`` wraps whatever is assigned to a ``FileField`` in
    a ``FieldFile``, and leaves ``_committed = False`` while that wrapper still
    holds the uploaded file. An unchanged value — the common case on any save
    that does not touch the file — is committed, and reading it costs a network
    round trip to S3: ``.size`` is a HeadObject, ``.seek()`` a GetObject. Both
    raise ``FileNotFoundError`` when the object is gone, which turns an
    unrelated save into a 500:

        POST /admin/authentication/customuser/1/change/ -> 500
        FileNotFoundError: File does not exist: media/avatars/.../student.jpg

    That happens whenever a bucket and a database disagree — an object deleted
    out from under a row, or production data restored against a local MinIO that
    has no media in it.

    Re-validating a stored file buys nothing anyway: it passed these same
    validators when it was uploaded, and stored bytes do not change afterwards.

    The default is False, so a plain ``UploadedFile`` — which carries no
    ``_committed`` attribute at all — is still validated.
    """
    return getattr(file, '_committed', False)
