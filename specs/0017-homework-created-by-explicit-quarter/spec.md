---
id: 0017
slug: homework-created-by-explicit-quarter
title: Homework author as created_by, and an explicit quarter mirrored with SubjectAssignment
status: in-progress
owner: bekzhan
created: 2026-11-10
updated: 2026-11-10
supersedes:
---

# 0017 — Homework `created_by` and an explicit, mirrored quarter

## Problem

`Homework.teaching_assignment` (FK to `TeachingAssignment`, `SET_NULL` per
spec 0014 G-6) is used for two things, and is a poor fit for both:

- **Authorship.** The serializer's `teacher`, the `?teacher=` filter, the
  per-teacher homework list and the admin all reach the author through
  `teaching_assignment.teacher`. Purging the teacher's assignment to the
  offering erases the author (`teacher: null`) even though the teacher still
  exists.
- **Quarter.** `teaching_assignment.quarter` looks like the homework's
  quarter but nothing reads it. The quarter that governs access is the
  `SubjectAssignment` mirror's `quarter` (`homework_access_quarter`). The two
  drift as soon as `due_date` is edited into another quarter, because only the
  mirror is updated.

The quarter itself is computed from dates in several places:

- `SubjectAssignment.save()` derives `quarter` from `date` and the academic
  year's `qN_start`/`qN_end` bounds whenever it is `None`
  (`derive_quarter()` → `AcademicYear.quarter_of`).
- `homework_sync.assignment_from_homework` resets the mirror's quarter to
  `None` whenever `due_date` moves, so it is re-derived from the date — losing
  any quarter that was set explicitly.
- `quarter_for_date_or_single_assignment` (create and update of both
  homework and subject assignments) derives the quarter from the date, falling
  back to the teacher's single assigned quarter.

As a result, a homework whose date lies outside the quarter bounds (or whose
year has no bounds) ends up with `quarter = None`, which makes `can_edit`
false for every teacher, and a date edit silently moves a homework between
quarters and therefore between teachers.

## Goals

- G-1 Record a homework's author as `Homework.created_by`, an FK to the
  `Teacher` profile (`SET_NULL`), replacing `Homework.teaching_assignment`.
- G-2 Give `Homework` its own stored `quarter` (1–4), set explicitly by the
  client.
- G-3 `Homework.quarter` and its `SubjectAssignment` mirror's `quarter` are one
  value: an edit on either side is reflected on the other, like the other
  mirrored fields of spec 0005.
- G-4 Remove date-based quarter derivation from every `SubjectAssignment`
  write path (all categories, not only homework). A quarter is only ever what
  a client or a migration set.

## Non-goals

- Changing who may edit, delete or grade a homework. Write access stays
  "a teacher assigned to the homework's offering for the homework's quarter"
  (`can_manage_homework`); it does **not** become creator-only.
- Validating `due_date` / `date` against the quarter's start/end bounds. The
  quarter and the date are independent; a homework may be due after its
  quarter ends.
- Removing `AcademicYear.quarter_of` or the year's quarter bounds. They stay
  for other uses (e.g. `current_quarter`, calendars); only their use to fill
  in an assignment's quarter on write goes.
- Changing `TeachingAssignment` or temporal teaching assignments (spec 0015).
- Moving a homework to another offering (still fixed after creation).
- Any frontend work beyond the API contract below.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Homework admin shows/searches/edits `created_by` and `quarter` instead of `teaching_assignment`. Read-only API reach unchanged. |
| Teacher | Must send `quarter` when creating a homework or a subject assignment. A due-date edit no longer moves the homework to another quarter. Author survives removal from the offering. |
| HomeroomTeacher | Same as Teacher where they teach the offering; otherwise no change. |
| Student | No change (response gains `quarter`; `teacher` still shown). |
| Supervisor | No change beyond the extra `quarter` field in responses. |
| Principal | No change beyond the extra `quarter` field in responses. |
| Parent | No change beyond the extra `quarter` field in responses. |

## Acceptance criteria

Author:

- **AC-1** — Given a teacher assigned to an offering for quarter 2, when they
  `POST /homeworks/` with `quarter: 2`, then every created homework has
  `created_by` = that teacher's `Teacher` profile.
- **AC-2** — Given a homework created by teacher T, when T's
  `TeachingAssignment` to that offering is purged (hard-deleted), then the
  homework's `created_by` is still T and the API's `teacher` is still
  `{id: T.user_id, full_name: …}`.
- **AC-3** — Given a homework whose `created_by` teacher is hard-deleted,
  then the homework survives with `created_by = NULL` and the API returns
  `teacher: null`.
- **AC-4** — Given homeworks by teachers A and B, when listing with
  `?teacher=<A's Teacher pk>` and via `teachers/<A's Teacher pk>/homeworks/`,
  then only A's homeworks are returned (ids keep their current meaning).
- **AC-5** — `Homework` no longer has a `teaching_assignment` field, and the
  API response no longer contains `teaching_assignment`.

Quarter on create:

- **AC-6** — Given a teacher assigned to an offering for quarter 3, when they
  `POST /homeworks/` with `quarter: 3` and any `due_date` (inside, outside, or
  with no quarter bounds on the year), then the homework and its mirror both
  have `quarter = 3`.
- **AC-7** — When `POST /homeworks/` omits `quarter`, then the response is 400
  and no homework is created.
- **AC-8** — Given a teacher assigned only for quarter 1, when they
  `POST /homeworks/` with `quarter: 2`, then the response is 403 and nothing
  is created (multi-offering batch fails as a whole, as today).
- **AC-9** — When `POST /subject-assignments/` (any category, including
  `homework`) omits `quarter`, then the response is 400; the quarter is never
  derived from `date`.

Quarter on update:

- **AC-10** — Given a homework in quarter 2, when its `due_date` is edited to
  a date inside quarter 3's bounds without sending `quarter`, then both the
  homework and its mirror stay in quarter 2.
- **AC-11** — Given a teacher assigned for quarters 2 and 3, when they update
  a quarter-2 homework with `quarter: 3`, then both the homework and its
  mirror have `quarter = 3`.
- **AC-12** — Given a teacher assigned only for quarter 2, when they update a
  quarter-2 homework with `quarter: 3`, then the response is 403 and nothing
  changes.
- **AC-13** — Given a homework, when its mirror is updated through
  `PATCH /subject-assignments/<id>/` with a new `quarter`, then
  `Homework.quarter` takes the same value.
- **AC-14** — Given a non-homework `SubjectAssignment` in quarter 1, when its
  `date` is edited to a date in quarter 4's bounds without sending `quarter`,
  then its quarter stays 1.
- **AC-15** — Saving a `SubjectAssignment` with `quarter = None` through the
  model leaves it `None` (no `derive_quarter()` fallback in `save()`).

Access follows the stored quarter:

- **AC-16** — Given a homework with `quarter = 2` whose `due_date` is outside
  every quarter's bounds, then the quarter-2 teacher sees `can_edit: true` and
  may edit, delete and grade it; a teacher assigned only for quarter 1 gets
  403.

Migration and consistency:

- **AC-17** — Given existing homeworks before the migration, after it each has
  `created_by = teaching_assignment.teacher` (or `NULL` where the FK was
  `NULL`), and `quarter` = its mirror's `quarter`, falling back to the old
  `teaching_assignment.quarter` where the mirror's is `NULL`; the mirror is
  then given the same value.
- **AC-18** — `sync_homework_assignments` reports a homework whose `quarter`
  differs from its mirror's as a mismatch, and `--fix` copies the homework's
  quarter onto the mirror (Homework stays the source of truth, spec 0005).

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/homeworks/` | Teacher assigned to every offering for `quarter` | `quarter` **required** (1–4). |
| PUT | `/api/v1/homeworks/<id>/` | Teacher assigned for the stored quarter, and for the new one if `quarter` is sent | `quarter` optional; omitted keeps the stored value. |
| GET | `/api/v1/homeworks/…` (all lists, detail, student/teacher lists) | unchanged | Response gains `quarter`, loses `teaching_assignment`. `teacher` unchanged in shape. `?teacher=` unchanged in meaning (see Open questions). |
| POST | `/api/v1/subject-assignments/` | unchanged | `quarter` **required** for every category. |
| PATCH | `/api/v1/subject-assignments/<id>/` | unchanged | `quarter` optional; omitted keeps the stored value; never derived from `date`. A homework mirror's change propagates to the Homework. |

<details>
<summary>Request / response shapes</summary>

```json
// POST /api/v1/homeworks/
{
  "offerings": [12, 13],
  "description": "Ex. 4–7",
  "max_grade": 10,
  "due_date": "2026-11-20",
  "quarter": 2,
  "is_active": true
}

// Homework in responses
{
  "id": 41,
  "offering": 12,
  "description": "Ex. 4–7",
  "teacher": {"id": 7, "full_name": "…"},   // from created_by; null if unset
  "quarter": 2,
  "max_grade": 10,
  "due_date": "2026-11-20",
  "is_active": true,
  "can_edit": true
}
```

</details>

## Data model

- `apps/lesson/models.py` — `Homework`:
  - remove `teaching_assignment`;
  - add `created_by = FK(Teacher, on_delete=SET_NULL, null=True,
    blank=True, related_name='homeworks')`;
  - `quarter = PositiveSmallIntegerField(null=True, blank=True,
    validators 1–4)` (already added in the working tree). Nullable only for
    legacy rows whose mirror had no quarter; the API never writes `NULL`.
  - `SCHOOL_CONSISTENT_FIELDS` becomes `('offering', 'created_by')`, as
    `TeachingAssignment` already checks `('offering', 'teacher')`.
- `apps/home/models.py` — `SubjectAssignment.save()` no longer calls
  `derive_quarter()`; `derive_quarter()` is removed if nothing else uses it.
- `apps/lesson/homework_sync.py` — field map gains
  `Homework.quarter <-> SubjectAssignment.quarter`; the "reset quarter when
  the date moves" rule goes.
- `apps/home/teaching_assignments.py` — `quarter_for_date_or_single_assignment`
  is no longer used on write paths (removed if unused).
- Migration: additive (`created_by`, `quarter`) → data backfill (AC-17) →
  destructive (drop `teaching_assignment`). Reversible: the reverse backfill
  picks the creator's live `TeachingAssignment` for `(offering, quarter)`
  where one exists, else `NULL`.
- Legacy non-homework `SubjectAssignment` rows with `quarter = NULL` are left
  as they are; no last date-derived backfill.

## Permissions

1. **Route-level** — unchanged; homework and subject-assignment endpoints keep
   their existing role gates.
2. **Object-level** — `can_manage_homework` and `request_can_write` keep the
   rule "assigned to `(offering, quarter)`", but read `Homework.quarter`
   instead of annotating the mirror's quarter. Changing the quarter needs an
   assignment for both old and new quarter. Admin/Supervisor/Principal stay
   read-only for homework writes, as today.
3. **View-level** — querysets unchanged except the `?teacher=` filter and the
   per-teacher list, which filter on `created_by` instead of
   `teaching_assignment__teacher`.

## Non-functional

- **Performance** — reading `Homework.quarter` directly drops the
  `access_quarter` subquery from homework lists; `teacher` needs
  `select_related('created_by')` to stay N+1-free.
- **Security** — no new PII; `created_by` exposes only what `teacher` already
  exposes. The 403 on quarter changes (AC-12) prevents a teacher from moving a
  homework into a quarter they do not teach.
- **Migrations** — three steps in one deploy; no downtime expected (homework
  row counts are small). The destructive step is the drop of
  `teaching_assignment`.
- **Clients** — breaking: clients that omit `quarter` on create (homework and
  subject assignment) now get 400. Frontend must ship the field first or in
  the same release.

## Resolved questions

- `?teacher=` and `teachers/<teacher_id>/homeworks/` keep taking a `Teacher`
  pk; they filter on `created_by_id`. The response's `teacher.id` stays the
  user id, as today.
- Legacy homework quarter: the mirror's, else the old
  `teaching_assignment.quarter` (AC-17). This makes rows that nobody could
  edit editable again by their quarter's teacher.
- Legacy non-homework assignments without a quarter: left `NULL`.
- Tenancy: `created_by` is in `SCHOOL_CONSISTENT_FIELDS`.
- Earlier specs: 0017 amends 0005 (quarter row of the field map), 0011 (G-2,
  AC-4 and the "no quarter on Homework" non-goal) and 0014 (G-6). They are
  not marked `superseded`; the rest of each still stands.

## Open questions

- [ ] None.
