---
spec: 0013
status: done
updated: 2026-10-15
---

# 0013 — Implementation plan

> Written ahead of approval at the owner's request. If the spec changes,
> update it first. Never let the plan silently redefine the behaviour.

## Approach

Extend the existing `SoftDeleteMixin` (`core/models.py`) rather than adding a
second mechanism. `Lesson` and the achievement models already use it.

**Rejected alternatives:**

- **A third-party package** (`django-safedelete`): it would fight
  `ScopedSoftDeleteManager` and the tenancy checks.
- **Postgres rules or triggers:** they would be invisible to Django and to the
  tests.

### Core mechanism (`core/models.py`, new `core/soft_delete.py`)

**`SoftDeleteMixin`:**

- Gains `deletion_batch = UUIDField(null=True, db_index=True)`.
- `delete(user=None)` calls `soft_delete(user)`.
- `soft_delete(user=None)` collects the cascade tree and stamps every row in it
  with one shared batch UUID.
- `restore()` restores every row that shares this row's `deletion_batch`.
- `hard_delete()` calls Django's `Model.delete()`. Only purge uses it.

**Tree walker** (`collect_soft_delete(objs)`): it walks `_meta.related_objects`
and only considers live rows.

| Edge | What the walker does |
|---|---|
| `CASCADE` | Includes the child's live rows and recurses into them. |
| `PROTECT` / `RESTRICT` with a live dependent | Raises `ProtectedError`. |
| `SET_NULL` / `DO_NOTHING` | Leaves the row untouched, so restore relinks it for free. |

The walker also handles two special cases:

- A row that was already deleted keeps its old batch.
- A model can add rows that no FK links to by overriding
  `soft_delete_extra()`. Uses:
  - `Homework` adds its mirror `SubjectAssignment`. The mirror is found by
    `detail_id`, not by a FK.
  - `HomeworkGrade` and `SubjectGrade` add each other's mirror.

**Stamping:** one `_base_manager.filter(pk__in=…).update(is_deleted=True,
deleted_at=…, deleted_by=…, deletion_batch=…)` per model, inside
`transaction.atomic`. Using `update()` skips `save()` on purpose. That avoids
the `QuarterGradeSnapshot` guard and the homework sync echo.

**`SoftDeleteQuerySet`:** all managers are built from it with
`Manager.from_queryset`. It provides:

- `delete()`: a soft delete.
- `hard_delete()`
- `restore()`
- `alive()`
- `dead()`

**Restore guards:** checked inside `atomic`.

1. If any `CASCADE` parent of the batch root is still deleted, raise
   `ValidationError` and name the parent.
2. Run the `UPDATE`. On `IntegrityError` from a partial unique index, roll back
   and raise `ValidationError`, naming the live row that conflicts.

**Registry:** `soft_delete_models()` returns every concrete subclass of the
mixin. The trash page, restore and the system check use it.

### Managers

- Models that now declare `objects = SchoolScopedManager()` drop that line.
  They inherit `objects`, `all_objects` and `unscoped` from the mixin.
  - `objects` stays the first manager, so reverse relations and the admin get
    live rows only.
  - Forward FKs use `_base_manager`, so `grade.student` still resolves when
    the student has been deleted.
- `MinorClassGroupManager` is rebased onto the soft-delete manager.
- `CustomUser`:
  - `objects` becomes `SoftDeleteUserManager`: a `UserManager` filtered to
    live rows. `ModelBackend.get_by_natural_key` and the JWT `get_user` call
    go through it, so a deleted user can't be found and therefore can't log in.
  - `in_school` becomes scoped and filtered.
  - `all_objects` is added.
- `School` is out of scope (AC-15) and keeps its managers unchanged.

## Files to touch

| File | Change |
|---|---|
| `core/models.py` | Extend `SoftDeleteMixin`; managers from `SoftDeleteQuerySet` |
| `core/soft_delete.py` (new) | Tree walker, batch restore, registry |
| `core/checks.py` | Add `softdelete.E001` (AC-12). Let `check_scoped_models_have_a_scoped_manager` and `UNSCOPED_DEFAULT_MANAGER` accept the new manager classes |
| `core/admin_mixins.py` | `has_unscoped_default_manager` recognises `SoftDeleteUserManager`. New `SoftDeleteAdminMixin`, described under Admin trash |
| `core/admin_trash.py` (new) | Trash views |
| `core/admin.py` | Wire the trash URLs into the AdminSite `get_urls` |
| `apps/templates/admin/base_site.html` | "Trash" link; trash templates under `apps/templates/admin/trash/` |
| `core/settings.py` | `SILENCED_SYSTEM_CHECKS = ['auth.E003']`, with a comment |
| `apps/authentication/models.py` | Mixin on `CustomUser`, profiles and `PsychologicalState`; `username` override plus partial constraint |
| `apps/authentication/admin.py` | `SchoolAdmin.has_delete_permission` returns `False` for everyone; drop `_has_dependents` (AC-15) |
| `apps/home/models.py` | Mixin on the models in scope; partial constraints; remove the `TeachingAssignment.delete` override (lines 484-493). `SubjectAssignment.delete` keeps the 0007 refusal and then soft-deletes |
| `apps/lesson/models.py` | Mixin on the models in scope; partial constraints; `Homework.teaching_assignment` becomes `SET_NULL, null=True`; file removal moves from `Homework.delete` to `hard_delete`; `soft_delete_extra()` on `Homework`, `HomeworkGrade` and `SubjectGrade` |
| `apps/lesson/homework_sync.py`, `apps/lesson/management/commands/sync_homework_assignments.py` | Mirror deletes are soft. The command ignores deleted rows |
| `apps/lesson/api/serializers.py:885`, `apps/lesson/admin.py:126` | Guard against a `NULL` `teaching_assignment` |
| `apps/achievement/models.py` | `Club.soft_delete` (line 354) calls `super()`; `unique_active_club_attendance` includes `is_deleted=False` |
| `apps/student_report/models.py`, `apps/notification/models.py` | Mixin |
| API delete sites | Pass `user=request.user` to `delete()`. The sites are listed under API delete sites |
| `apps/*/admin.py` | Add `SoftDeleteAdminMixin` to every ModelAdmin of a model in scope |

**`SoftDeleteAdminMixin`:**

- The changelist shows live rows.
- Delete and "delete selected" soft-delete and record the acting user.
- The delete confirmation page shows the tree from the walker.

**API delete sites:**

- `apps/home/api/views/{assignments,quarter_grades,students}.py`
- `apps/home/repo/subject.py`
- `apps/lesson/api/{views,homework,attendance_views}.py`
- `apps/lesson/services.py`
- `apps/authentication/api/views.py`

### Partial unique constraints

| Model | Current | Becomes partial |
|---|---|---|
| `CustomUser` | `username` field-unique | `user_unique_live_username` |
| `AcademicYear` | `unique_year_per_school`, `one_active_per_school` | Both get `is_deleted=False` added |
| `TeachingAssignment` | `unique_together (offering, teacher)` | Named partial constraint |
| `HomeroomTeacherAssignment` | `unique_together (class_group)` | Named partial constraint |
| `Enrollment` | `unique_active_enrollment_per_class_group` | Gets `is_deleted=False` added |
| `QuarterGrader` | `(subject, quarter)` | Named partial constraint |
| `SubjectAssignment` | `subjectassignment_unique_detail` | Gets `is_deleted=False` added |
| `SubjectGrade` | `(assignment, student)` | Named partial constraint |
| `QuarterGrade` | `(student, offering, quarter)` | Named partial constraint |
| `Topic` | `(lesson, parent, title)` | Named partial constraint |
| `TopicGrade` | `(topic, student)` | Named partial constraint |
| `SubjectSchedule` | `(offering, quarter)` | Named partial constraint |
| `ScheduleSession` | `(schedule, time_start, time_end, weekday)` | Named partial constraint |
| `ScheduleAttendance` | `scheduleattendance_one_per_slot` | Gets `is_deleted=False` added |
| `HomeworkGrade` | `(homework, student)` | Named partial constraint |
| `ClubAttendance` | `unique_active_club_attendance` | Check it; add `is_deleted=False` if missing |

These constraints are left alone:

- `*_id_school_unique` (unconditional, because the composite FKs reference it)
- `School.uuid` and `School.slug` (`School` is out of scope)
- Profile `OneToOneField(user)`

Upserts go through the live manager, so after a soft delete they create a new
row alongside the deleted one. Audit these:

- the `get_or_create` / `update_or_create` calls in `homework_sync`
- `Enrollment.enroll_student`
- `ClassGroupCollection` creation

### Read-path audit (AC-10)

Default managers do **not** cover these cases:

- `annotate` and `aggregate` across reverse relations (`Avg('grades__grade')`,
  `Count('grades')`)
- `filter(child__…)`
- `Exists` and `Subquery`
- `.values()` that crosses relations
- `_base_manager`
- `.raw()`

When the parent is deleted, the cascade already covers its children. The leak
is a deleted child of a **live** parent.

Grep these places for the patterns above:

- `apps/home/grading.py`
- `apps/home/repo/`
- `apps/home/services*.py`
- `apps/home/api/views/`
- `apps/lesson/services.py`
- `apps/lesson/api/`
- `apps/student_report/`
- `apps/achievement/`

Wherever a soft-deletable child is aggregated or joined, add
`child__is_deleted=False` or `filter=Q(...)`. Each site gets a test.

### Admin trash

- `/admin/trash/`: deleted-row counts per model in the registry, with the
  queryset scoped to the active school.
- `/admin/trash/<app>/<model>/`: rows grouped by `deletion_batch`. Each group
  shows `deleted_at`, `deleted_by`, the batch root and its child count.
- `POST …/batch/<uuid>/restore/`: calls `restore()` on the batch root. A guard
  error is shown as an admin error message.
- `POST …/batch/<uuid>/purge/`:
  1. A confirmation page lists the batch.
  2. On confirm, `hard_delete()` runs on the root rows. Postgres cascades the
     real children, and `Homework.hard_delete` removes the stored files.
  3. Only superusers and the Admin group may purge.

## Migrations

```bash
python manage.py makemigrations authentication home lesson student_report notification achievement
python manage.py migrate
```

- Additive columns. `is_deleted` defaults to `False`, and the other columns
  are nullable.
- In the same migration as the columns, remove `unique_together` / field
  `unique` and add the partial `UniqueConstraint`. Each app's migration runs in
  one transaction.
- The history tables of `HistoricalRecords` models (`Lesson`, `Topic`,
  `TopicGrade`, `Enrollment`) get the new columns automatically.
- `AlterField` for `Homework.teaching_assignment`.
- No backfill.
- CI runs `makemigrations --check --dry-run`.

## Test plan

| AC | Test | File |
|---|---|---|
| AC-1 | `test_ac1_delete_sets_is_deleted_and_hides_row` (parametrized over the registry) | `core/tests/test_soft_delete.py` |
| AC-2 | `test_ac2_offering_delete_cascades_one_batch_and_restores` | `apps/home/tests/test_soft_delete_cascade.py` |
| AC-3 | `test_ac3_previously_deleted_child_stays_deleted_on_restore` | `apps/home/tests/test_soft_delete_cascade.py` |
| AC-4 | `test_ac4_restore_child_of_deleted_parent_refused` | `apps/home/tests/test_soft_delete_cascade.py` |
| AC-5 | `test_ac5_unique_value_reusable_after_delete[<constraint>]` | `core/tests/test_soft_delete_unique.py` |
| AC-6 | `test_ac6_deleted_user_cannot_authenticate` | `apps/authentication/tests/test_soft_delete_user.py` |
| AC-7 | `test_ac7_teaching_assignment_delete_keeps_homework` | `apps/lesson/tests/test_homework_soft_delete.py` |
| AC-8 | `test_ac8_homework_files_kept_until_purge` | `apps/lesson/tests/test_homework_soft_delete.py` |
| AC-9 | `test_ac9_queryset_and_admin_bulk_delete_are_soft` | `core/tests/test_soft_delete.py` |
| AC-10 | `test_ac10_<site>_excludes_deleted_grade` (one per audited site) | Per app |
| AC-11 | `test_ac11_trash_lists_restores_purges_scoped` | `core/tests/test_admin_trash.py` |
| AC-12 | `test_ac12_check_flags_hard_cascade_child` | `core/tests/test_soft_delete_checks.py` |
| AC-13 | `test_ac13_protect_dependent_blocks_soft_delete` | `core/tests/test_soft_delete.py` |
| AC-14 | `test_ac14_homework_assignment_direct_delete_still_refused` | `apps/home/tests/test_soft_delete_cascade.py` |
| AC-15 | `test_ac15_school_cannot_be_deleted_in_app` | `apps/authentication/tests/test_soft_delete_user.py` |

Existing tests that assert real removal will need updating. Look for these
patterns:

- `_base_manager` counts after a delete
- `TeachingAssignment.delete` removing homework
- Homework delete removing files

## Order of work

1. Core: mixin, queryset, walker, restore, registry and the check, with their
   tests.
2. Apply the mixin, managers and partial constraints per app (authentication →
   home → lesson → student_report / notification / achievement), with
   migrations.
3. `Homework` FK change, sync, file handling.
4. Record the acting user at the API delete sites; read-path audit.
5. `SoftDeleteAdminMixin` and the trash views.
6. Mark the spec shipped. Add a note to 0005 pointing at this spec.

## Rollout

- No new env vars.
- Deploy order: the migration and the code ship together. The code relies on
  the new columns, and the old code would fail on the new partial constraints
  only on upserts against deleted rows, which cannot exist yet.
- Rollback: reverse the migrations. Before reversing, any soft-deleted rows
  that duplicate a live row's unique value must be purged, otherwise the old
  full constraints fail to rebuild.

## Risks

| Risk | Mitigation |
|---|---|
| Aggregates leak deleted children | Read-path audit plus AC-10 tests |
| A new CASCADE child is added later as a hard-delete model | `softdelete.E001` fails `manage.py check` in CI |
| `update()`-based stamping skips signals and history | Stated as a non-goal. Nothing in scope relies on `post_delete` except avatar/file cleanup, which moves to purge |
| `auth.E003` silenced hides a real problem later | A comment in settings points at this spec, and AC-5/AC-6 cover login and uniqueness |
| `PROTECT` from snapshots blocks deleting students, offerings or the admin who froze | Accepted by the owner (spec, Resolved questions) |
