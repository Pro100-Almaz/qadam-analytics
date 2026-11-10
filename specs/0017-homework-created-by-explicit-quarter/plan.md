---
spec: 0017
status: in-progress
updated: 2026-11-10
---

# 0017 — Implementation plan

## Approach

`Homework` gets `created_by` (FK `Teacher`, `SET_NULL`) and its own `quarter`,
and loses `teaching_assignment`. `quarter` joins the spec 0005 field map in
`homework_sync`, so it moves with the other mirrored fields in both
directions; the "reset the quarter when the date moves" rule goes.
`SubjectAssignment.save()` stops deriving the quarter, and
`quarter_for_date_or_single_assignment` is deleted with its four call sites.
Create endpoints require `quarter`; update endpoints keep the stored one when
it is omitted.

Access reads `Homework.quarter` directly. The `access_quarter` subquery on
the mirror goes: homework lists filter on `quarter`, grade lists on
`homework__quarter`.

Rejected: keeping the quarter only on the mirror and annotating it (today's
shape). The spec asks for the two to be one mirrored value, and a stored
column removes a subquery from every homework and grade list.

Rejected: `created_by` as a user FK. Every consumer (`?teacher=`, the
per-teacher list, the admin) works in `Teacher` ids.

## Files to touch

| File | Change |
|---|---|
| `apps/lesson/models.py` | `created_by`, `quarter`; drop `teaching_assignment`; `SCHOOL_CONSISTENT_FIELDS` |
| `apps/lesson/migrations/0032_…`, `0033_…`, `0034_…` | add fields → backfill → drop FK |
| `apps/lesson/homework_sync.py` | `quarter` in the field map both ways; `create_homework_with_assignment(created_by=, quarter=)` |
| `apps/home/models.py` | `SubjectAssignment.save()` no longer derives; drop `derive_quarter()` |
| `apps/home/teaching_assignments.py` | drop `quarter_for_date_or_single_assignment` |
| `apps/lesson/api/serializers.py` | `quarter` on create (required) / write (optional) / read; drop `teaching_assignment`; `teacher` from `created_by` |
| `apps/lesson/api/homework.py` | create/put use the sent quarter; access on `quarter`; filters on `created_by` |
| `apps/home/api/serializers.py` | `quarter` required on subject-assignment create |
| `apps/home/api/views/assignments.py` | create/patch use the sent or stored quarter |
| `apps/lesson/admin.py` | `created_by`, `quarter` instead of `teaching_assignment` |
| `core/factories.py` | `HomeworkFactory` sets `created_by`/`quarter` from a `teaching_assignment` parameter |

No repo/service-layer split is added: the code being changed lives in the
API modules and `homework_sync` already, and moving it is out of scope.

## Migrations

- 0032 additive: `created_by`, `quarter` (the working-tree field).
- 0033 data: AC-17 backfill, reversible as the spec describes.
- 0034 destructive: remove `teaching_assignment`.
- CI's `makemigrations --check` must stay clean.

## Test plan

New module `apps/lesson/tests/test_homework_created_by_quarter.py`, one test
per AC, named `test_acN_…`. AC-17 lives in
`apps/lesson/tests/test_homework_created_by_migration.py` (MigrationExecutor,
like `test_homework_assignment_migration.py`). Existing tests that encoded
date derivation (spec 0011) are updated to the new rule, not deleted silently.

## Rollout

- No env vars.
- Breaking for clients that omit `quarter` on create: frontend first or same
  release.
- Rollback: reverse the three migrations (the backfill is reversible).

## Risks

| Risk | Mitigation |
|---|---|
| Other writers relied on `save()` deriving the quarter (admin, scripts) | grep showed only the API, `homework_sync` and the 0029 migration write `SubjectAssignment`; the migration uses historical models and is unaffected |
| Tests encoding spec 0011 derivation break | update them to the 0017 rule and say so |
