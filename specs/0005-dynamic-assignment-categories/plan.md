---
spec: 0005
status: done
updated: 2026-09-30
---

# 0005 — Implementation plan

## Approach

`AssignmentCategory` is a new shared table. `SubjectAssignment.category` becomes
a `PROTECT` FK to it, and the column is converted in place by a data migration.
`detail_id` is a plain integer. `SubjectAssignment.DETAIL_MODELS` maps a
category code to its detail model (only `homework` → `lesson.Homework` today),
and `save()` enforces the checks from AC-6 to AC-11.

Sync lives in `apps/lesson/homework_sync.py`. It is called from the `save()`
and `delete()` overrides on `Homework`, `HomeworkGrade`, `SubjectAssignment`
and `SubjectGrade`. Every override takes `sync=True`, and the sync functions
save the counterpart with `sync=False`, so a write never bounces back. Lookups
inside sync use `_base_manager`: the counterpart is the same school by
construction, and sync can run outside a request scope (admin, commands).

Rejected: Django signals (the spec forbids them); a real `GenericForeignKey`
(a content-type column adds nothing when the category already decides the
model); syncing from views only (admin and scripts would drift).

## Files to touch

| File | Change |
|---|---|
| `apps/home/models.py` | `AssignmentCategory`; `SubjectAssignment` FK, `detail_id`, `is_active`, checks, sync hooks; `SubjectGrade` hooks; `TeachingAssignment.delete` |
| `apps/lesson/models.py` | `Homework` / `HomeworkGrade` save/delete hooks; `Homework.delete()` also removes stored attachment files, so the API, admin, sync and `TeachingAssignment.delete` paths all clean up |
| `apps/lesson/homework_sync.py` | new: the sync functions and the drift report |
| `apps/lesson/admin.py` | bulk deletes go through `delete()` so they sync |
| `apps/lesson/management/commands/sync_homework_assignments.py` | new: `--check` / `--fix` |
| `apps/home/api/serializers.py`, `apps/home/api/views/assignments.py` | slug category, homework create, drafts filter, categories endpoint |
| `apps/lesson/api/homework.py` | bulk-create sync, shared delete |
| `apps/lesson/api/analytics_subject.py` | categories from the DB, drafts excluded |
| `apps/student_report/services/grade_sheet.py` | `category.code`, drafts excluded |
| `apps/home/admin.py` | `AssignmentCategoryAdmin` |
| `core/checks.py` | `home.AssignmentCategory` in `SHARED_MODELS` |
| `core/factories.py` | `AssignmentCategoryFactory`, `HomeworkFactory`, `HomeworkGradeFactory` |

## Migrations

- `home/0041_assignment_category` — create and seed the table, add a nullable
  `category_ref` FK.
- `home/0042_assignment_category_copy` — copy each row's code into the FK.
- `home/0043_assignment_category_fk` — drop the old column, rename, make NOT
  NULL, add `detail_id`, `is_active` and the constraint.
  Split because Postgres refuses to ALTER a table in the transaction that just
  updated it with deferred FK checks pending. All three are reversible.
- `lesson/0029_homework_subject_assignment_backfill` — mirror existing homework
  and grades. The reverse deletes the mirrors.

## Test plan

- `apps/home/tests/test_assignment_categories.py` — AC-1 to AC-11
- `apps/lesson/tests/test_homework_assignment_sync.py` — AC-13 to AC-25
- `apps/lesson/tests/test_homework_assignment_migration.py` — AC-4, AC-12
