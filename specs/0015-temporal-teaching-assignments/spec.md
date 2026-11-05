---
id: 0015
slug: temporal-teaching-assignments
title: Temporal teaching assignments and grade authority
status: shipped
owner:
created: 2026-11-03
updated: 2026-11-04
supersedes:
---

# 0015 — Temporal teaching assignments and grade authority

## Problem

Changing the teacher FK of an existing `TeachingAssignment` erases who taught
an offering before the change. Creating a replacement assignment instead does
not currently help: every live assignment grants access to the whole offering,
so the replacement teacher can change earlier grades and the former teacher's
authority cannot be limited to the dates they taught.

## Goals

- G-1 Preserve each teacher's inclusive teaching period without rewriting or
  deleting an earlier assignment, except a superseded replacement that would
  otherwise represent no more than one teaching day.
- G-2 Limit teacher grade reads and writes to academic work dated inside one of
  that teacher's assignment periods.
- G-3 Let former teachers finish and correct work from their own period until
  the academic year is archived.
- G-4 Keep every grade and assignment change attributable to its acting user.

## Non-goals

- Scheduling a future replacement. A replacement is immediate or backdated.
- Recovering teacher changes made before this spec; no historical TA data
  exists from which to reconstruct them.
- Giving homeroom teachers write access to subjects they do not teach.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Replaces a TA instead of changing its teacher; may make audited corrections. |
| Teacher | Reads and writes work inside any of their TA periods. |
| HomeroomTeacher | Existing cross-subject access remains read-only. |
| Student | No permission change. |
| Supervisor | Existing read access remains unchanged. |
| Principal | Existing read access remains unchanged. |
| Parent | No permission change. |

## Acceptance criteria

- **AC-1** — Given an open TA for T, when an admin replaces T with NT on day
  D, then T's row remains with `end_date=D-1` and a new NT row has
  `start_date=D`, `end_date=NULL`.
- **AC-2** — Given an existing TA, when its teacher, offering, role or start
  date is changed, then validation refuses the change; replacement never
  changes those fields in place.
- **AC-3** — Given two different teachers, overlapping open TAs for the same
  offering and role are allowed; overlapping periods for the same teacher and
  offering are rejected.
- **AC-4** — Given work dated inside T's closed TA period, T can read, create,
  edit and delete its grades until the academic year is archived.
- **AC-5** — Given work dated before NT's start date, NT receives 403 for grade
  writes and does not gain teacher-scoped reads to it.
- **AC-6** — Given work dated after T's end date, T receives 403 for grade
  writes and does not gain teacher-scoped reads to it.
- **AC-7** — Given several TAs covering the same effective date, every one of
  those teachers can grade the work.
- **AC-8** — Given a final quarter grade, only teachers whose TA covers the
  configured quarter end date can create, change or delete it.
- **AC-9** — Given an assignment, lesson or homework without an effective
  date, teacher grading is refused until it has a date.
- **AC-10** — Given a teacher-authorized assessment, changing its effective
  date outside that teacher's periods is refused.
- **AC-11** — Given an archived academic year, all teacher grade writes are
  refused while an admin correction with a reason is recorded in history.
- **AC-12** — Given homework/subject-grade mirrors, writes through either API
  apply the same temporal permission and preserve the same actor.
- **AC-13** — Existing TAs in an active, non-archived year backfill from the
  first configured quarter start with no end date; archived-year TAs backfill
  through the last configured quarter end. If legacy quarter boundaries are
  absent, the migration derives September 1 through August 31 from a
  `YYYY/YYYY` (or equivalent separated) academic-year label.
- **AC-14** — Given an open TA for NT with `start_date=D`, when closing it for
  a replacement would produce `end_date <= start_date`, then the NT row is
  hard-deleted and the OT row is created open on the requested effective date.
  Earlier closed rows remain unchanged.

## API contract

Existing grade and assignment endpoints keep their request shapes. Teacher
writes additionally enforce temporal object permission and return HTTP 403
when the effective date is outside the caller's TA periods.

TA serializers add `start_date`, `end_date` and `is_current`. Relevant grade
and assessment read payloads add `can_edit` so clients can hide unavailable
controls; the server-side check remains authoritative.

## Data model

- `TeachingAssignment.start_date` is required.
- `TeachingAssignment.end_date` is nullable; `NULL` means the current open TA.
- Both bounds are inclusive; a closed range must have
  `end_date >= start_date`. Quarter boundaries determine quarter-grade
  authority but do not constrain legacy assessment dates.
- The same teacher cannot have overlapping live periods for one offering.
  Different teachers may overlap, including in the same role.
- TA and mutable grade models retain audit history with the acting user.

## Permissions

1. **Route-level** — Existing teacher-only grade routes remain teacher-only;
   admin corrections are performed through the audited admin path.
2. **Object-level** — Ordinary grade authority uses lesson date for topic
   grades, assignment date for subject grades, homework due date for homework
   grades, and configured quarter end for final quarter grades.
3. **View-level** — Teacher querysets include only work whose effective date is
   covered by one of the caller's TAs. Existing homeroom reads remain additive
   and read-only.

## Non-functional

- **Performance** — Temporal filters use indexed offering/teacher/date fields
  and are applied in SQL, without per-row permission queries in list views.
- **Security** — Dates are checked again on writes; client `can_edit` is never
  trusted as authorization.
- **Migrations** — Backfill prefers configured quarter boundaries and falls
  back to the year label for older calendars. It refuses ambiguous labels.
  Previously overwritten teachers need manual historical rows.

## Open questions

- None.
