"""Copy media files from local disk into the MinIO bucket.

Driven by what the database actually references rather than by walking
MEDIA_ROOT, so orphaned files are left behind and nothing referenced is
missed. Every FileField/ImageField on every installed model is discovered
automatically, so new upload fields need no changes here.

Safe to run repeatedly: objects already present in the bucket are skipped
unless --overwrite is passed. Nothing is deleted from local disk.

A one-time backfill for media that predates the move to S3 storage. It builds
the target storage from the S3_* env vars directly rather than from the app's
configured default, so it can run against any bucket.

    python -m scripts.migrate_media_to_minio --dry-run
    python -m scripts.migrate_media_to_minio
    python -m scripts.migrate_media_to_minio --verify-only

In Docker:

    docker compose exec appseed-app python -m scripts.migrate_media_to_minio
"""
import argparse
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from django.apps import apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.core.files.storage import FileSystemStorage  # noqa: E402
from django.db.models import FileField  # noqa: E402
from storages.backends.s3 import S3Storage  # noqa: E402


def iter_file_fields():
    """Yield (model, field) for every FileField/ImageField in the project."""
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        for field in model._meta.get_fields():
            if isinstance(field, FileField):
                yield model, field


def referenced_names(model, field):
    """Distinct non-empty stored paths for one file field."""
    manager = getattr(model, "all_objects", None) or model._default_manager
    qs = manager.all()
    names = qs.exclude(**{field.name: ""}).exclude(
        **{f"{field.name}__isnull": True}
    ).values_list(field.name, flat=True).distinct()
    return sorted({n for n in names if n})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be copied, change nothing")
    parser.add_argument("--verify-only", action="store_true",
                        help="only check which referenced files are in the bucket")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-upload objects that already exist in the bucket")
    args = parser.parse_args()

    options = dict(settings.S3_STORAGE_OPTIONS)
    if not options.get("endpoint_url"):
        sys.exit("S3_ENDPOINT_URL is not set - configure the S3_* env vars first.")

    source = FileSystemStorage(location=settings.MEDIA_ROOT)
    # file_overwrite must be on, or S3Storage renames colliding keys and the
    # paths in the database stop matching what is in the bucket.
    target = S3Storage(**{**options, "file_overwrite": True})

    if args.verify_only:
        mode = "verify"
    elif args.dry_run:
        mode = "dry-run"
    else:
        mode = "copy"

    print(f"source: {settings.MEDIA_ROOT}")
    print(f"target: {options['endpoint_url']}/{options['bucket_name']}"
          f"/{options.get('location', '')}")
    print(f"mode:   {mode}\n")

    copied = skipped = absent = failed = 0

    for model, field in iter_file_fields():
        names = referenced_names(model, field)
        if not names:
            continue
        label = f"{model._meta.label}.{field.name}"
        print(f"{label} ({len(names)} referenced)")

        for name in names:
            in_target = target.exists(name)

            if args.verify_only:
                if in_target:
                    skipped += 1
                else:
                    absent += 1
                    print(f"  MISSING IN BUCKET  {name}")
                continue

            if in_target and not args.overwrite:
                skipped += 1
                continue

            if not source.exists(name):
                absent += 1
                print(f"  MISSING ON DISK    {name}")
                continue

            if args.dry_run:
                copied += 1
                print(f"  would copy         {name}")
                continue

            try:
                with source.open(name, "rb") as fh:
                    target.save(name, fh)
                copied += 1
                print(f"  copied             {name}")
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"  FAILED             {name}: {exc}")

    print()
    if args.verify_only:
        print(f"in bucket: {skipped}   missing: {absent}")
    else:
        print(f"copied: {copied}   already present: {skipped}   "
              f"missing on disk: {absent}   failed: {failed}")

    return 1 if (failed or absent) else 0


if __name__ == "__main__":
    sys.exit(main())
