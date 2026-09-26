---
spec: 0004
updated: 2026-09-26
---

# 0004 — Tasks

Ordered and small enough to land individually. Each task names the AC it
serves, so nothing gets implemented that the spec did not ask for.

**How test-first and a green suite fit together:** a test task adds its tests
marked `@pytest.mark.xfail(strict=True, reason="0004 T-n")`. The suite stays
green, and the test *must* fail until the code lands. The implementation task
that follows removes the marker. `strict=True` turns an unexpected pass into a
failure, so a marker cannot be forgotten.

New test files:

- `apps/lesson/tests/test_attendance_single_record.py` (called
  `single_record` below)
- `apps/lesson/tests/test_attendance_single_record_migration.py` (called
  `migration` below)

The analytics tests go in the existing
`apps/lesson/tests/test_analytics_attendance_api.py` (called `analytics`
below).

## A. Schema: one record per slot, plus audit columns

- [x] **T-1** (AC-1, AC-6) — Tests, xfail:
  - `test_ac1_db_rejects_second_row_for_same_slot` in `single_record`.
  - `test_ac6_migration_keeps_newest_row_per_slot` in `migration`. It runs with
    `django_db(transaction=True)` and a local `migrate_to()` fixture built on
    `MigrationExecutor`. It migrates to `lesson 0027`, inserts duplicates with
    distinct `created_at` plus an equal-`created_at` pair that tests the `id`
    tiebreak, then migrates to `0028`.
- [x] **T-2** (AC-1, AC-12) — Model changes on `ScheduleAttendance` in
  `apps/lesson/models.py`:
  - `Meta.constraints = [UniqueConstraint(fields=['session', 'student', 'date'], name='scheduleattendance_one_per_slot')]`.
  - `marked_by`: FK `settings.AUTH_USER_MODEL`, `null=True`, `SET_NULL`,
    `related_name='+'`, and not added to `SCHOOL_CONSISTENT_FIELDS`.
  - `updated_at`: `auto_now=True, null=True`.

  *Lands in the same commit as T-3. A model without its migration fails CI's
  drift check.*
- [x] **T-3** (AC-1, AC-6, AC-12) — Migration generation, as its own task:
  - `makemigrations lesson --name scheduleattendance_one_per_slot` produces
    `0028`, with `AddField` ×2 and `AddConstraint`.
  - Then hand-insert `RunPython(collapse_duplicates, RunPython.noop)`
    **before** `AddConstraint`: a `ROW_NUMBER() OVER (PARTITION BY session_id,
    student_id, date ORDER BY created_at DESC, id DESC)` delete that prints
    the deleted count.
  - The docstring states that the data step is irreversible.
  - Remove the T-1 xfail markers.
  - Verify with `makemigrations --check --dry-run`, which must report no
    drift.

## B. Write path: POST updates an existing record

- [x] **T-4** (AC-2, AC-3, AC-7, AC-12, AC-13) — Tests in `single_record`,
  xfail:
  - `test_ac2_post_to_recorded_slot_updates_it_and_returns_200`
  - `test_ac3_post_to_empty_slot_creates_and_returns_201`. This one passes
    today, so it is **not** xfail; it guards the kept behaviour.
  - `test_ac7_parent_sees_one_present_row_after_correction`
  - `test_ac12_save_records_marked_by_and_updated_at`. It covers POST create,
    POST update by a second user, PATCH, and a pre-existing factory row that
    stays `null`.
  - `test_ac13_register_resave_applies_the_changed_mark`. It POSTs every
    student of a session in which some already have records and one flips
    absent → present, then asserts that all responses are 200/201.
- [x] **T-5** (AC-2, AC-12) — `record_attendance(session, student, date,
  attendance_status, user) -> (attendance, created)` in `apps/lesson/services.py`, built
  on `ScheduleAttendance.objects.update_or_create(session=…, student=…,
  date=…, defaults={'status': status, 'marked_by': user})`.
- [x] **T-6** (AC-2, AC-3, AC-7, AC-12, AC-13) — Wire it in:
  - `ScheduleAttendanceWriteSerializer.validate()`: run the duplicate check
    only when `self.instance is not None`.
  - `ScheduleAttendanceListCreateAPIView.post`: call `record_attendance()` and
    return 201 when created, 200 when updated.
  - PATCH saves with `marked_by=request.user`.
  - `ScheduleAttendanceSerializer` gains read-only `marked_by` and
    `updated_at`.
  - Remove the T-4 xfail markers.
- [x] **T-7** (AC-4) — Tests in `single_record`:
  - `test_ac4_racing_posts_leave_one_row_with_last_status`: two threads with
    `transaction=True` behind a `threading.Barrier`.
  - A deterministic companion that patches the first lookup so the create hits
    the constraint, then asserts that the loser's status is applied.

  These are **not** xfail: T-5's `update_or_create` should already satisfy
  them. If either fails, fix `record_attendance()` in this task (for example
  with an explicit `IntegrityError` retry). Do not relax the test.
- [x] **T-8** (AC-5) — Test `test_ac5_patch_onto_occupied_slot_is_400_and_changes_nothing`
  in `single_record`. The serializer check already returns 400, so this test
  is **not** xfail.
- [x] **T-9** (AC-5) — `ScheduleAttendanceDetailAPIView.patch`: catch
  `IntegrityError` and return 400 with the same message, as a backstop when a
  PATCH races an insert. It is covered by an extra case in the T-8 test that
  bypasses the serializer check via patching.

## C. Read path: stable order and a null rate when nothing is recorded

- [x] **T-10** (AC-8) — Test `test_ac8_student_list_order_is_stable_on_ties`
  in `single_record`, xfail. It needs two rows tied on `(date, time_start,
  time_end)`, which means two sessions with the same times.
- [x] **T-11** (AC-8) — `StudentAttendanceListAPIView.get`: `order_by('-date',
  'session__time_start', 'session__time_end', 'id')`. Remove the xfail.
- [x] **T-12** (AC-9, AC-10, AC-11) — Tests in `analytics`:
  - `test_ac9_unrecorded_rate_is_null_in_every_block`, xfail. It checks
    summary totals and by_subject/by_weekday/by_month, heatmap
    row/column/totals, and the overview blocks.
  - `test_ac10_unrecorded_students_excluded_from_class_stats`, xfail.
  - `test_ac10_overview_lists_unrated_students_last_without_rank`, xfail.
  - `test_ac11_recorded_rate_formula_unchanged`. It passes today, so it is
    **not** xfail.
- [x] **T-13** (AC-9, AC-10) — `apps/lesson/api/analytics_attendance.py`:
  - `counts()` returns `attendance_rate=None` when `present + absent == 0`.
  - Add a `rated(values)` helper that drops `None`.
  - `_class_comparison`: use rated rates, and set `rank`/`percentile`/`delta`
    to `None` when the own rate is `None`.
  - Overview: sort key `(rate is None, -(rate or 0), full_name)`, `rank=None`
    for unrated students, and `mean_student_rate` over rated rates only.
  - Leave `analytics_common.py` untouched.
  - Update the existing assertions that this redefines, with a comment citing
    AC-9/AC-10: `analytics:145`, `:206-208` (if the cohort has a zero-row
    student), `:419-423` and `:470`.
  - Remove the T-12 xfail markers.
- [x] **T-14** (AC-9, AC-10) — Contract and docs:
  - The analytics serializers get `allow_null=True` on `attendance_rate`,
    `class_attendance_rate`, `class_mean_rate`, `delta` and
    `mean_student_rate`, plus `IntegerField(allow_null=True)` for `rank` and
    `percentile`.
  - Rewrite the module docstring's "Counting semantics" paragraph to say "a
    student with nothing recorded reads a rate of null".

## Done when

- [x] Every AC has a passing test. AC-1 to AC-13 are covered by T-1, T-4, T-7,
  T-8, T-10 and T-12, and no xfail markers remain.
- [x] `pytest` green
- [ ] `ruff check .` clean — **not met, pre-existing**: the repo has 858 findings at HEAD. This change adds only RUF012 on `Meta.constraints` and the migration's lists, matching every other model and migration here
- [x] `makemigrations --check --dry-run` reports no drift
- [x] `python manage.py check` and `SCHOOL_SCOPE_MODE=enforce python manage.py check` green
- [x] `python scripts/check_specs.py` green
- [ ] PR description records the production probe count (expected 0) and the
  `pg_dump` taken before deploy
- [ ] Frontend team confirmed that `attendance_rate: null` is handled before
  deploy (plan § Rollout step 2)
- [ ] Spec `status:` set to `shipped`
