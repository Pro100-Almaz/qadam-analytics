---
id: 0004
slug: attendance-single-record-per-slot
title: One attendance record per lesson slot — parents see the teacher's latest mark
status: in-progress
owner: almaz
created: 2026-09-25
updated: 2026-09-26
---

# 0004 — One attendance record per lesson slot

## Problem

Clients report that a teacher marks a student **present**, yet the parent's
view says the student **missed** the class.

**Confirmed cause: the teacher's correction is rejected, and the rejection is
invisible.**

1. **POST cannot update.** `ScheduleAttendanceWriteSerializer.validate()`
   (`apps/lesson/api/serializers.py:824`) rejects a POST for a
   `(session, student, date)` that already has a record, with **400**
   `{"non_field_errors":["Attendance for this student on this date is already recorded."]}`.
2. **The teacher client always POSTs the whole register.** Production nginx
   logs from 2026-09-21 to 2026-09-24 show bursts of 5–14 POSTs to one session
   within a second, and every one returned 400 with an 86-byte body, which is
   exactly that message. When a teacher re-saves a register to change one mark,
   every student who already has a record is rejected, and so is the changed
   one. Some bursts cover several sessions at once (Sep 24, 06:58 UTC: sessions
   559, 235, 237, 564), which looks like a day-level save.
3. **Records are often written before the lesson.** One affected student's
   rows show whole school days written within 1–2 seconds, sometimes hours
   ahead of the lesson (Sep 24, 10:49 local, for lessons up to 14:10) or the
   day before (Sep 15 for Sep 16). Whoever pre-marks the day, the teacher's
   later correction then collides with the existing record and is lost.
4. **The client does not surface the 400**, so the teacher believes the mark
   was saved, while the parent reads the earlier `absent`.

Checked and **not** the cause:

- **Duplicate rows.** Production has **0** duplicate `(session, student, date)`
  groups (queried 2026-09-25). The app-level check has no DB constraint behind
  it, so a race could still create one; that is hardening here, not the bug.
- **Read scoping.** School scope, subgroup routing, academic-year mismatch
  (`SubjectOffering.academic_year` is derived from `class_group`), caching,
  auto-created absent rows and `ClubAttendance` were all ruled out in the
  trace.

Contributing read-side defects fixed alongside:

- **Unstable list order.** `StudentAttendanceListAPIView`
  (`apps/lesson/api/attendance_views.py:897`) orders by
  `-date, session__time_start, session__time_end` with no tiebreak.
- **Ambiguous rate.** `ratio()` (`apps/lesson/api/analytics_common.py:176`)
  returns `0.0` when nothing is recorded, so `attendance_rate: 0.0` means both
  "never registered" and "always absent".
- **No record of who marked what.** Nothing links a record to the user who
  wrote it, so the pre-marking pattern above could not be attributed from the
  database.

## Goals

- G-1 A lesson slot `(session, student, date)` holds at most one attendance
  record, enforced by the database.
- G-2 Marking a student for a slot that already has a record updates that
  record, so the teacher's latest mark wins. A duplicate is never created and
  the teacher gets no error.
- G-3 Existing duplicates are collapsed to the most recent record.
- G-4 A parent (or anyone else) reading attendance gets a stable order and
  sees exactly one status per slot.
- G-5 An attendance rate is `null` when nothing was recorded, so "no data" can
  no longer be read as "0% attended".
- G-6 Every attendance record says who last marked it and when.

## Non-goals

- **Frontend changes.** The parent and teacher apps live outside this repo.
  G-5 changes the API contract. The frontend must handle `null`, and that work
  is tracked outside this spec.
- A bulk "mark the whole class" endpoint.
- **Rejecting marks for future lessons.** Pre-marking stays allowed; with
  upsert the subject teacher can correct it.
- **Precedence between markers.** The last save wins, whoever makes it (a
  homeroom teacher's later bulk save overwrites a subject teacher's mark). No
  role takes priority.
- A full change history. G-6 keeps only the *last* marker. A history of every
  change belongs to security backlog item #7.
- Changing `ratio()` for **grade** analytics. Only attendance rates change.
- Inferring absence from unrecorded slots. An unrecorded slot stays
  unrecorded.
- `ClubAttendance`, which is a separate feature.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Same write rules; a POST to an already-recorded slot now updates it instead of returning 400 |
| Teacher | Same as Admin, for the teacher's own offerings |
| HomeroomTeacher | Same as Admin, for their homeroom class and its подгруппы |
| Student | Reads one status per slot; rate is `null` when nothing is recorded |
| Supervisor | Same as Admin |
| Principal | Same as Admin |
| Parent | Reads the teacher's latest mark; one status per slot; rate is `null` when nothing is recorded |

## Acceptance criteria

- **AC-1** — Given an existing `ScheduleAttendance` for `(session, student,
  date)`, when a second row for the same triple is inserted directly through
  the ORM, then the database raises `IntegrityError`.
- **AC-2** — Given a student marked `absent` for a slot, when the teacher POSTs
  `present` for the same `(session, student, date)`, then the response is
  **200**, its body carries the existing row's `id` with `status: "present"`,
  and exactly one row exists for that slot.
- **AC-3** — Given no record for a slot, when the teacher POSTs, then the
  response is **201** and one row exists (current behaviour, kept).
- **AC-4** — Given two concurrent POSTs for the same slot with different
  statuses, when both complete, then exactly one row exists, neither request
  returns 5xx, and its status is the one from the request that committed
  last.
- **AC-5** — Given a PATCH that changes a row's `date` or `student` onto a slot
  that already has another record, then the response is **400** and neither
  row changes. PATCH never silently merges two rows.
- **AC-6** — Given duplicate rows for a slot before the migration, when the
  migration runs, then only the row with the latest `created_at` survives (the
  highest `id` breaks a tie) and the others are deleted. The migration reports
  how many rows it deleted.
- **AC-7** — Given a parent of the student, when they GET
  `students/<id>/attendance/` after AC-2, then the slot appears exactly once
  with `status: "present"`.
- **AC-8** — Given two rows with equal `date`, `time_start` and `time_end`,
  when the student attendance list is read twice, then both reads return the
  same order. The tiebreak is `id`.
- **AC-9** — Given a student with no recorded attendance in the requested
  scope, when the attendance summary is read, then `totals.attendance_rate` is
  `null` and `totals.recorded` is `0`. The same holds for every
  `by_subject` / `by_weekday` / `by_month` block, heatmap summary and
  class-overview block whose `recorded` is 0.
- **AC-10** — Given a class where some students have no records, when
  `class_comparison` is computed, then those students are left out of
  `class_mean_rate`, `rank` and `percentile` rather than counted as 0%. If the
  student's own rate is `null`, `rank`, `percentile` and `delta` are `null`.
  In the class-group overview, those students stay in `students`, sorted after
  every rated student, with `rank: null`. They are also left out of
  `totals.mean_student_rate`. *(Amended 2026-09-25 during planning; approved
  by the owner.)*
- **AC-11** — Given a student with recorded rows, then `attendance_rate` is
  unchanged from today (`present / (present + absent)` × 100, 2 dp).
- **AC-12** — Given a teacher who POSTs or PATCHes an attendance record, then
  the record's `marked_by` is that user and `updated_at` is the time of the
  save. A later save by another user replaces both. Records that existed before
  the migration keep `marked_by` and `updated_at` as `null`. The read
  serializer exposes `marked_by` (user id) and `updated_at`.
- **AC-13** — Given a register re-save (POST for every student of a session,
  some of which already have records, one changed from `absent` to
  `present`), then every response is 200 or 201, and the changed student reads
  `present`. This is the production scenario.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/schedule-sessions/<session_id>/attendance/` | Teacher (own offering), HomeroomTeacher, Admin, Supervisor, Principal | **Changed:** upsert on `(session, student, date)`. 201 when created, 200 when an existing row was updated. Sets `marked_by` / `updated_at` |
| PATCH | `/api/v1/attendance/<pk>/` | same | Unchanged; 400 on moving onto an occupied slot |
| GET | `/api/v1/students/<student_id>/attendance/` | `can_access_student` | **Changed:** order adds `id` tiebreak |
| GET | `/api/v1/analytics/students/<id>/attendance-summary/`, `/api/v1/analytics/offerings/<id>/attendance-heatmap/`, `/api/v1/analytics/class-groups/<id>/attendance-overview/` | unchanged | **Changed:** `attendance_rate` is `null` when `recorded == 0` |

<details>
<summary>Response shapes</summary>

POST to an occupied slot, which used to return 400 and now returns 200:

```json
{"id": 812, "session": 44, "student": 1031, "date": "2026-09-24",
 "status": "present", "...": "..."}
```

Attendance counts block with nothing recorded:

```json
{"recorded": 0, "present": 0, "absent": 0, "attendance_rate": null}
```

</details>

## Data model

- `apps/lesson/models.py` — `ScheduleAttendance.Meta` gains
  `UniqueConstraint(fields=['session', 'student', 'date'], name='scheduleattendance_one_per_slot')`.
- `ScheduleAttendance.marked_by`: FK to `authentication.CustomUser`,
  `null=True`, `on_delete=SET_NULL`, `related_name='+'`.
- `ScheduleAttendance.updated_at`: `DateTimeField(auto_now=True, null=True)`.
  It is null for existing rows until their next save.
- Migration, in two steps within one migration file (or two files):
  1. a `RunPython` that collapses duplicates per AC-6. Its reverse is a no-op,
     since deleted rows cannot be restored.
  2. `AddConstraint`.
- **Destructive:** deletes duplicate rows. Production had 0 on 2026-09-25.
  Re-run the probe below just before deploying, and record the count in the
  PR.
- **Additive:** the two nullable audit columns. No backfill.

```sql
SELECT session_id, student_id, date, COUNT(*), array_agg(status ORDER BY created_at)
FROM lesson_scheduleattendance GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;
```

## Permissions

1. **Route-level** — unchanged (`IsTeacherAdminOrSupervisor` on POST/PATCH).
2. **Object-level** — unchanged: `can_manage_schedule()` gates the write, and
   the upsert updates a row only on a session the caller could already write.
   The existing row's session is the requested session, so no new rights are
   granted.
3. **View-level** — unchanged: `attendance_queryset()` parent/student branches.

## Non-functional

- **Concurrency** — the upsert must be race-safe. It relies on the DB
  constraint (`update_or_create` inside `transaction.atomic`, retrying once on
  `IntegrityError`, or an `INSERT … ON CONFLICT` equivalent). A
  check-then-insert is not acceptable.
- **Performance** — no new queries on the read paths. The constraint's index
  also serves the slot lookup.
- **Tenancy** — the constraint is not school-scoped, and doesn't need to be:
  `session` already belongs to exactly one school. `SCHOOL_SCOPE_MODE=enforce`
  must stay green.
- **Migrations** — irreversible data step; brief lock on
  `lesson_scheduleattendance` while the constraint builds.

## Trace findings

- The first trace ranked duplicate rows as the most likely cause. Production
  data falsified that: there are 0 duplicate groups.
- One affected student's records (student 331, Sep 14–25) showed whole days
  written in one second, often before the lesson.
- nginx 400s with an 86-byte body confirmed that corrections are rejected with
  "already recorded".
- Evidence file: `.omc/specs/deep-dive-trace-clients-facing-the-problem-with.md`
  (local, not committed).

## Open questions

- [x] ~~Run the probe query on production.~~ 0 duplicates (2026-09-25). The
      cause is rejected corrections; see Problem.
- [ ] Which parent screen and endpoint shows "missed"? The frontend team needs
      to confirm, and must handle `attendance_rate: null` (AC-9) before this
      ships.
- [x] ~~Does the teacher client PATCH or POST to correct a mark?~~ It POSTs
      the whole register (nginx logs). AC-5's PATCH 400 stays as a guard but
      is not on the hot path.
- [ ] Frontend: the teacher client should surface a failed save. That is not
      this repo, but after this spec lands the corrections that used to fail
      stop failing.
