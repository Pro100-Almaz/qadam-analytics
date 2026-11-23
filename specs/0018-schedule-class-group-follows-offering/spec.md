---
id: 0018
slug: schedule-class-group-follows-offering
title: SubjectSchedule.class_group always follows its offering
status: shipped
owner: bekzhan
created: 2026-11-23
updated: 2026-11-23
supersedes:
---

# 0018 — `SubjectSchedule.class_group` always follows its offering

## Problem

`SubjectSchedule` stores its class group in two places: its own `class_group`
FK and, when it has one, `offering.class_group`. Nothing keeps the two in
sync, and the production dump of 2026-11-18 (848 schedules) shows they have
drifted apart:

| Rows | State |
|---|---|
| 628 | offering-bound, `class_group` matches the offering |
| 21 | offering-bound, `class_group` **disagrees** with the offering (all live, ~800 attendance rows hang off them) |
| 196 | offering-bound, `class_group = NULL` — ids 1–199, created before migration `0024_subjectschedule_class_group` (2026-09-02) added the column without a backfill |
| 3 | free entries (no offering) carrying their own `class_group` |

Most of the 21 pair a major-class offering with a schedule placed on a
подгруппа (e.g. offering "Music Rus" @ MA, schedule on "Music 2MA"); two
are the reverse ("Science grade 5" offering, schedule on KZ(rus) / KZ(kaz)).
None of those подгруппы has its own offering for the subject.

The disagreement is visible because read paths are split: some use
`class_group` (the "other sessions" overlay in
`apps/lesson/services.py:build_other_sessions_map`, class attendance
analytics), others `offering__class_group` (role visibility, the
`academic_year` filter, ordering). A drifted or NULL row therefore shows up
under one class in one screen and another class — or nowhere — in the next.

The drift has three sources:

- `SubjectScheduleWriteSerializer` derives `class_group` from the offering
  only when the request omits it; a PATCH of `class_group` alone on an
  offering-bound schedule is not re-checked against the stored offering.
- Model `save()` (scripts, factories, admin) enforces nothing.
- Editing `SubjectOffering.class_group` (allowed in `SubjectOfferingAdmin`)
  leaves the offering's schedules behind.

## Goals

- G-1 Every offering-bound schedule's `class_group` equals
  `offering.class_group`, existing rows included.
- G-2 The rule holds on every write path: the schedule API, model `save()`,
  and edits to the offering's class group.

## Non-goals

- Removing `SubjectSchedule.class_group`. Free entries (no offering) need it.
- Rewriting read paths that use `offering__class_group` (visibility,
  `academic_year` filter, ordering, analytics). After the backfill both give
  the same answer for offering-bound rows; consolidating them is a separate
  spec.
- Changing free-entry visibility or write permissions.
- Re-pointing the 21 drifted schedules to подгруппа offerings or splitting
  them. They move to their offering's class group, as the offering says.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Schedule POST/PATCH no longer 400s on a mismatching `class_group`; the offering's wins. The 21 drifted schedules move to their offering's class group. |
| Teacher | Same API change for schedules they may manage. |
| HomeroomTeacher | The 21 drifted schedules (and the 196 legacy rows in the overlay) now appear under the offering's class group. |
| Student | Unchanged — visibility already went through `offering__class_group`. |
| Supervisor | As Admin. |
| Principal | As Admin. |
| Parent | Unchanged, as Student. |

## Acceptance criteria

- **AC-1** — Given schedules with an offering whose `class_group` is NULL or
  differs from `offering.class_group` (soft-deleted ones included), when the
  data migration runs, then every one has `class_group_id =
  offering.class_group_id`, and free entries keep their `class_group`.
- **AC-2** — Given an offering in class group A, when a schedule is POSTed
  with that offering and `class_group = B`, then the response is 201 and the
  stored and returned `class_group` is A.
- **AC-3** — Given an offering in class group A, when a schedule is POSTed
  with that offering and no `class_group`, then the stored `class_group` is A.
- **AC-4** — Given an offering-bound schedule in class group A, when it is
  PATCHed with only `class_group = B`, then the stored `class_group` stays A.
- **AC-5** — Given a schedule on an offering in A, when it is PATCHed to an
  offering in C (with or without a different `class_group`), then the stored
  `class_group` is C.
- **AC-6** — Given an offering-bound schedule, when it is PATCHed with
  `offering: null` and a `description`, then it becomes a free entry that keeps
  the sent `class_group`, or its stored one when none is sent; without a
  `description` the PATCH is a 400.
- **AC-7** — Given an offering with live and soft-deleted schedules, when the
  offering's `class_group` is changed and saved, then all of its schedules
  have the new `class_group`.
- **AC-8** — Given an offering in A, when a `SubjectSchedule` is saved through
  the ORM with that offering and `class_group = B`, then the stored
  `class_group` is A.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/subject-schedules/` | Teacher, Admin, Supervisor | `class_group` is ignored when `offering` is set |
| PATCH | `/api/v1/subject-schedules/<pk>/` | Teacher, Admin, Supervisor | `class_group` is ignored when the resulting schedule has an offering |

The 400 `{"class_group": ["Must match the offering's class group."]}` is
removed. `class_group` stays required for free entries. Response shapes are
unchanged.

## Data model

- `apps/lesson/models.py` — `SubjectSchedule.save()` copies
  `offering.class_group_id` into `class_group_id` when an offering is set.
- `apps/home/models.py` — `SubjectOffering.save()` cascades a changed
  `class_group_id` to all of the offering's schedules (soft-deleted included),
  in the same transaction.
- Migration: data-only `RunPython` backfill in `apps/lesson`, over all rows
  (`_base_manager`). No schema change. The reverse is a no-op — the previous
  values were wrong and are not restored. `school` is unaffected, since the
  offering and its class group share a school.

## Permissions

1. **Route-level** — unchanged (`IsTeacherAdminOrSupervisor` on writes).
2. **Object-level** — unchanged; `can_manage_schedule` /
   `can_manage_offering_schedule` still decide on the offering.
3. **View-level** — unchanged querysets. Forcing `class_group` from the
   offering cannot widen access, since writes are authorised on the offering.

## Non-functional

- **Performance** — the backfill is one `UPDATE` (~220 rows in prod). The
  cascade is one `UPDATE` and runs only when the class group actually changes.
- **Security** — no new exposure; see Permissions.
- **Migrations** — data-only, no downtime, forward-only in effect.

## Open questions

- [x] Are the NULL rows intentional? No — all are ids 1–199, created before
  the column existed. They are backfilled.
