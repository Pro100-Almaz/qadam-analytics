#!/usr/bin/env python3
"""Validate the frontmatter of every spec under specs/.

Standard library only, so it runs in CI without installing anything.
Exits non-zero if any spec is malformed.

    python scripts/check_specs.py
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"
DIR_RE = re.compile(r"^(\d{4})-([a-z0-9]+(?:-[a-z0-9]+)*)$")
STATUSES = {"draft", "approved", "in-progress", "shipped", "superseded"}
REQUIRED = ("id", "slug", "title", "status", "created")
# Directories under specs/ that hold supporting documents, not specs.
NON_SPEC_DIRS = {"templates", "backlog"}


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return the leading YAML frontmatter as a flat dict, or None if absent.

    Deliberately minimal: specs use flat `key: value` pairs only, so this
    avoids a PyYAML dependency.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        line = line.split("#", 1)[0].rstrip() if not line.startswith("#") else ""
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def check_spec(spec_dir: Path, errors: list[str], seen_ids: dict[str, Path]) -> dict | None:
    name = spec_dir.name
    match = DIR_RE.match(name)
    if not match:
        errors.append(f"{name}/: directory must be named NNNN-kebab-slug")
        return None
    dir_id, dir_slug = match.groups()

    spec_file = spec_dir / "spec.md"
    if not spec_file.exists():
        errors.append(f"{name}/: missing spec.md")
        return None

    fields = parse_frontmatter(spec_file.read_text(encoding="utf-8"))
    if fields is None:
        errors.append(f"{name}/spec.md: missing or unterminated --- frontmatter block")
        return None

    for key in REQUIRED:
        if not fields.get(key):
            errors.append(f"{name}/spec.md: frontmatter missing required key '{key}'")

    if fields.get("id") and fields["id"] != dir_id:
        errors.append(f"{name}/spec.md: id '{fields['id']}' does not match directory '{dir_id}'")
    if fields.get("slug") and fields["slug"] != dir_slug:
        errors.append(f"{name}/spec.md: slug '{fields['slug']}' does not match directory '{dir_slug}'")

    status = fields.get("status")
    if status and status not in STATUSES:
        errors.append(
            f"{name}/spec.md: status '{status}' is not one of {', '.join(sorted(STATUSES))}"
        )

    for key in ("created", "updated"):
        value = fields.get(key)
        if value:
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                errors.append(f"{name}/spec.md: {key} '{value}' is not a YYYY-MM-DD date")

    if dir_id in seen_ids:
        errors.append(f"{name}/: id {dir_id} already used by {seen_ids[dir_id].name}/")
    else:
        seen_ids[dir_id] = spec_dir

    if status == "approved" and not (spec_dir / "plan.md").exists():
        print(f"  note: {name}/ is approved but has no plan.md")

    return fields


def main() -> int:
    if not SPECS_DIR.is_dir():
        print(f"no specs/ directory at {SPECS_DIR}", file=sys.stderr)
        return 1

    spec_dirs = sorted(d for d in SPECS_DIR.iterdir() if d.is_dir() and d.name not in NON_SPEC_DIRS)
    if not spec_dirs:
        print("no specs yet — nothing to check")
        return 0

    errors: list[str] = []
    seen_ids: dict[str, Path] = {}
    rows = []
    for spec_dir in spec_dirs:
        fields = check_spec(spec_dir, errors, seen_ids)
        if fields:
            rows.append((fields.get("id", "????"), fields.get("status", "?"), fields.get("title", spec_dir.name)))

    for spec_id, status, title in rows:
        print(f"  {spec_id}  {status:<12} {title}")

    if errors:
        print(f"\n{len(errors)} problem(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"\n{len(rows)} spec(s) OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
