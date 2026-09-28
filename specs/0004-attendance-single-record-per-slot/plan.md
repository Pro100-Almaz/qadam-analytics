---
spec: 0004
status: done
updated: 2026-09-26
---

# 0004 — Implementation plan

> Written against an **approved** spec. If the spec changes, update it first —
> never let the plan silently redefine the behaviour.

## Approach

**Why:** production showed 0 duplicates. The client bug is the POST rejecting
corrections with 400 "already recorded" while the teacher client re-POSTs the
whole register (spec § Problem). The upsert is the fix. The constraint and
the race handling are hardening.

**Write side.** The database becomes the guard. `ScheduleAttendance` gets a
`UniqueConstraint` on `(session, student, date)`. POST becomes an upsert
through a new `record_attendance()` service built on
`ScheduleAttendance.objects.update_or_create()`:

- Django runs `update_or_create` inside `transaction.atomic()` with
  `select_for_update()`. When a concurrent insert wins the race, its
  `get_or_create` step catches the `IntegrityError` and re-reads the row.
- The losing request then locks that row and applies its own status, so the
  request that commits last wins (AC-4).
- The view returns 201 or 200 from the `created` flag.
- The serializer's `.exists()` duplicate check stays for PATCH only (AC-5). The
  constraint backs it up: an `IntegrityError` on PATCH becomes a 400.

**Read side.**

- The student attendance list gains an `id` tiebreak (AC-8).
- `counts()` in the attendance analytics returns `attendance_rate: None` when
  `present + absent == 0` (AC-9).
- Every place that feeds rates into `mean` / `rank` / `percentile_rank` first
  filters out `None` (AC-10).
- The shared helpers in `analytics_common.py` stay unchanged, because the grade
  analytics use them too (spec non-goal).

**Rejected alternatives**

- *Keep the 400 and add only the constraint.* This closes the duplicate hole,
  but a teacher correcting absent → present gets an error unless the frontend
  switches to PATCH. The owner chose upsert.
- *Hand-rolled `INSERT … ON CONFLICT DO UPDATE` via `RawSQL`.* It is one round
  trip, but it bypasses `SchoolConsistentModel.save()` validation and the
  scoped manager. `update_or_create` keeps both, and one extra query per mark
  is negligible.
- *Collapse duplicates at read time (`DISTINCT ON`).* This hides the symptom
  and leaves bad data. The analytics would still need the same dedupe in every
  tally.
- *Change `ratio()` to return `None`.* It is shared with the grade analytics,
  where `0.0` plus `lesson_count` is the documented contract. The change stays
  in the attendance `counts()` only.

## Files to touch

| File | Change |
|---|---|
| `apps/lesson/models.py` | `ScheduleAttendance.Meta.constraints = [UniqueConstraint(fields=['session', 'student', 'date'], name='scheduleattendance_one_per_slot')]`. Also add `marked_by` (FK `settings.AUTH_USER_MODEL`, `null=True`, `SET_NULL`, `related_name='+'`) and `updated_at` (`auto_now=True, null=True`). `marked_by` stays **out of** `SCHOOL_CONSISTENT_FIELDS`, because admin roles may act across schools |
| `apps/lesson/migrations/0028_scheduleattendance_one_per_slot.py` | `RunPython(collapse_duplicates, noop)` followed by `AddConstraint` (see Migrations) |
| `apps/lesson/services.py` | New `record_attendance(session, student, date, attendance_status, user) -> (attendance, created)`, a thin wrapper around `update_or_create` with `defaults={'status': attendance_status, 'marked_by': user}` (the parameter avoids shadowing `rest_framework.status`). Business logic lives here, not in the view |
| `apps/lesson/api/serializers.py` | `ScheduleAttendanceSerializer` gains read-only `marked_by` and `updated_at`. `ScheduleAttendanceWriteSerializer.validate()`: run the duplicate check only when `self.instance is not None`. PATCH saves with `marked_by=request.user`. Analytics serializers: `attendance_rate`, `class_attendance_rate`, `class_mean_rate`, `delta`, `mean_student_rate` get `allow_null=True`, and `rank`/`percentile` become `IntegerField(allow_null=True)`, so the OpenAPI schema says so |
| `apps/lesson/api/attendance_views.py` | `ScheduleAttendanceListCreateAPIView.post`: call `record_attendance()` and return 201/200. `ScheduleAttendanceDetailAPIView.patch`: catch `IntegrityError` and return 400. `StudentAttendanceListAPIView.get`: add `'id'` to `order_by` |
| `apps/lesson/api/analytics_attendance.py` | `counts()` returns `None` rate on 0 denominator. Add a `rated(values)` helper that drops `None`. `_class_comparison`: filter rates, and return null `rank`/`percentile`/`delta` when the own rate is `None`. Overview: sort unrated students last, `rank=None` for them, `mean_student_rate` over rated students only. Update the module docstring's "Counting semantics" paragraph |
| `apps/lesson/tests/…` | See the test plan |

Not touched:

- `apps/home/repo/`: attendance queries live in the lesson app, and this
  change adds no new query shape.
- `core/permissions.py`: permissions are unchanged (spec § Permissions).

## Migrations

```bash
docker compose -f docker-compose.dev.yml exec appseed-app python manage.py makemigrations lesson --name scheduleattendance_one_per_slot
docker compose -f docker-compose.dev.yml exec appseed-app python manage.py migrate
```

- **Additive:** `AddField` for `marked_by` and `updated_at`, both nullable,
  with no backfill.
- **Destructive.** The `RunPython` step deletes duplicate rows. Production had
  0 on 2026-09-25, so on production this step is expected to be a no-op.
  - Per `(session_id, student_id, date)` it keeps the row with the greatest
    `(created_at, id)` and deletes the rest. This is one `DELETE … WHERE id IN
    (…)` built from a `ROW_NUMBER() OVER (PARTITION BY session_id, student_id,
    date ORDER BY created_at DESC, id DESC)` subquery, via `schema_editor.execute`.
  - It prints the deleted count, which the migrate output shows (AC-6).
  - The reverse is `migrations.RunPython.noop`. Deleted rows are gone, and that
    is stated in the migration docstring.
- It uses the historical model / raw SQL, so `SchoolScopedManager` is not
  involved (`use_in_migrations = False` already).
- There is no backfill.
- CI's `makemigrations --check --dry-run` must stay clean.
- **Before deploy:** re-run the spec's probe query on production and put the
  duplicate count in the PR description. The expected count is 0.

## Test plan

Two new files:

- `apps/lesson/tests/test_attendance_single_record.py` for the write side and
  the list order.
- `apps/lesson/tests/test_attendance_single_record_migration.py` for the data
  step.

Rate-semantics tests go in the existing `test_analytics_attendance_api.py`.

| AC | Test | File |
|---|---|---|
| AC-1 | `test_ac1_db_rejects_second_row_for_same_slot` | `test_attendance_single_record.py` |
| AC-2 | `test_ac2_post_to_recorded_slot_updates_it_and_returns_200` | `test_attendance_single_record.py` |
| AC-3 | `test_ac3_post_to_empty_slot_creates_and_returns_201` | `test_attendance_single_record.py` |
| AC-4 | `test_ac4_racing_posts_leave_one_row_with_last_status` | `test_attendance_single_record.py` |
| AC-5 | `test_ac5_patch_onto_occupied_slot_is_400_and_changes_nothing` | `test_attendance_single_record.py` |
| AC-6 | `test_ac6_migration_keeps_newest_row_per_slot` | `test_attendance_single_record_migration.py` |
| AC-7 | `test_ac7_parent_sees_one_present_row_after_correction` | `test_attendance_single_record.py` |
| AC-8 | `test_ac8_student_list_order_is_stable_on_ties` | `test_attendance_single_record.py` |
| AC-9 | `test_ac9_unrecorded_rate_is_null_in_every_block` | `test_analytics_attendance_api.py` |
| AC-10 | `test_ac10_unrecorded_students_excluded_from_class_stats` and `test_ac10_overview_lists_unrated_students_last_without_rank` | `test_analytics_attendance_api.py` |
| AC-11 | `test_ac11_recorded_rate_formula_unchanged` | `test_analytics_attendance_api.py` |
| AC-12 | `test_ac12_save_records_marked_by_and_updated_at` | `test_attendance_single_record.py` |
| AC-13 | `test_ac13_register_resave_applies_the_changed_mark` | `test_attendance_single_record.py` |

How the harder tests work:

- **AC-4:** `@pytest.mark.django_db(transaction=True)`. Two threads POST
  `absent` and `present` through `record_attendance()` behind a
  `threading.Barrier`, then the test asserts exactly one row and no exception.
  Threads are nondeterministic, so a second, deterministic test forces the
  race path: patch the first lookup so the create hits the constraint, then
  assert that the loser's status is applied. If the threaded test proves flaky
  in CI, the deterministic test is the one that counts for AC-4.
- **AC-6:** `@pytest.mark.django_db(transaction=True)` with Django's
  `MigrationExecutor`. Migrate `lesson` to `0027`, insert duplicates through
  the historical model, migrate to `0028`, and assert the survivors. The repo
  has no migration-test helper, so this adds a small `migrate_to()` fixture
  local to the file.

**Existing tests that change on purpose** (AC-9 / AC-10 redefine them; they
are not regressions):

- `test_analytics_attendance_api.py:145`: an empty totals block now expects
  `attendance_rate: None`.
- `test_analytics_attendance_api.py:206-208`: `class_mean_rate`, `rank` and
  `percentile` are recomputed over rated students only. This applies only if
  the `cohort` fixture has a student with 0 rows; the implementer checks the
  fixture and updates the numbers, with a comment on why.
- `test_analytics_attendance_api.py:419-423` and `:470`: the same applies to
  the overview order, ranks and `mean_student_rate`.

A 0.0 rate for a student who has rows and was always absent (`:172`, `:260`,
`:343`) stays 0.0, and AC-11 guards it.

Gates, all of which must be green:

- `pytest`
- `python manage.py check`
- `SCHOOL_SCOPE_MODE=enforce python manage.py check`
- `python scripts/check_specs.py`

## Rollout

- **No new env vars.** `.env.production.example` is unchanged.
- **Deploy order:**
  1. Run the probe query on production and record the count.
  2. The frontend must tolerate `attendance_rate: null` (spec open question 2)
     **before** this deploys. Otherwise parent screens may render `null` as
     `NaN`% or crash.
  3. Deploy. The migration runs on container start (`docker/entrypoint.sh`).
- **Rollback:**
  - The code can roll back freely.
  - The constraint is dropped by migrating `lesson` back to `0027`.
  - Deleted duplicates cannot come back. Take a `pg_dump` of
    `lesson_scheduleattendance` before deploying (`backups/` is gitignored).

## Risks

| Risk | Mitigation |
|---|---|
| The teacher client may rely on the old 400 (e.g. it treats 400 as "already saved, skip") | The response changes from 400 to 200 with the updated row, which is a strict improvement. Tell the frontend team so they can drop any workaround. AC-13 reproduces the production burst |
| The last save wins, so a late homeroom bulk save overwrites a subject teacher's mark (owner accepted this, spec non-goal) | `marked_by` makes each case traceable in one query. Revisit with a precedence spec if clients complain |
| The frontend ships after the backend and shows `null` rates as 0/NaN/crash | Gate the deploy on the frontend confirming `null` handling (Rollout step 2) |
| `ScheduleAttendanceFactory` uses a random `date`, so a test that builds several rows for one student and session could collide with the new constraint | Faker's `date_object` spans decades, so collisions are rare. Tests that need several rows pass explicit dates. If flakes appear, switch the factory to `factory.Sequence` dates |
| The threaded AC-4 test is flaky on CI's Postgres | The deterministic race test covers AC-4. Mark the threaded one `@pytest.mark.flaky` only if needed, never skip it silently |
| Adding the constraint locks `lesson_scheduleattendance` for as long as the unique index takes to build | The table is small (daily registers per school). If production has more than 10⁶ rows, add the index `CONCURRENTLY` in a separate non-atomic migration first |
| Changes to `SchoolConsistentModel.save()` validation break under `update_or_create` | `update_or_create` calls `save()`, so validation still runs. The enforce-mode `manage.py check` plus the AC-2 test under an authenticated school-scoped client cover it |
