---
id: 0011
slug: subject-assignment-quarter
title: A quarter on every subject assignment, filterable on its endpoints
status: in-progress
owner: bekzhan
created: 2026-10-01
updated: 2026-10-01
supersedes:
---

# 0011 — A quarter on every subject assignment, filterable on its endpoints

## Problem

`SubjectAssignment` has no quarter. The only link to a quarter is its `date`,
compared against the `q1_start … q4_end` bounds of the academic year. To list
one quarter's work, a client first reads the year's bounds and then sends
`date_from` / `date_to`. If the bounds are missing, or edited later, an
assignment moves to another quarter or belongs to none.

## Goals

- G-1 `SubjectAssignment.quarter` (1–4, nullable) is stored on the row.
- G-2 When the client does not send a quarter, it is derived from `date`.
- G-3 `?quarter=N` filters every assignment and subject-grade list endpoint.

## Non-goals

- Recomputing quarters when an academic year's bounds change. Each row keeps
  the quarter it was given.
- A quarter on `Homework`. The homework mirror derives its quarter from
  `due_date`.
- Changing how `QuarterGrade` or `Lesson.quarter` work.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Teacher | May send `quarter` on create / PATCH. Sees `quarter` in responses and can filter by it. |
| HomeroomTeacher, Admin, Supervisor, Principal, Psychologist, Student, Parent | See `quarter` in responses and can filter by it. Visibility is unchanged. |

## Acceptance criteria

- **AC-1** — Every assignment payload carries `quarter` (1–4 or null).
- **AC-2** — On create without `quarter`, the quarter is the year quarter that
  contains `date`. If `date` is outside every quarter, it is null.
- **AC-3** — On create, an explicit `quarter` is stored as sent, for
  category `homework` too.
- **AC-4** — A PATCH that changes `date` without `quarter` derives the quarter
  again. A PATCH with `quarter` sets it.
- **AC-5** — `quarter` filters `GET subject-assignments/`,
  `my-class/subject-assignments/`, `subject-grades/`,
  `teachers/my-class/subject-grades/` and
  `offerings/<id>/subject-grades/`. An assignment with no quarter never
  matches.
- **AC-6** — A `quarter` outside 1–4 returns 400, both in a write body and as
  a filter.
- **AC-7** — When a Homework's `due_date` changes, its mirror's quarter is
  derived again. Other Homework edits leave the quarter alone.
- **AC-8** — The migration backfills existing rows from `date` and the year's
  bounds. Rows dated outside every quarter stay null.

## API contract

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/subject-assignments/` | New filter `quarter` |
| POST | `/api/v1/subject-assignments/` | New optional body field `quarter` |
| GET / PATCH | `/api/v1/subject-assignments/<pk>/` | `quarter` in response; PATCH accepts it |
| GET | `/api/v1/my-class/subject-assignments/` | New filter `quarter` |
| GET | `/api/v1/subject-grades/` | New filter `quarter` (on the assignment) |
| GET | `/api/v1/teachers/my-class/subject-grades/` | New filter `quarter` |
| GET | `/api/v1/offerings/<offering_id>/subject-grades/` | New filter `quarter` |

## Data model

- `apps/home/models.py` — `SubjectAssignment.quarter`,
  `PositiveSmallIntegerField(null=True, validators=1..4)`. `save()` fills it
  from `date` when it is null. New `AcademicYear.quarter_of(date)`.
- Migration `home/0045_subjectassignment_quarter` is additive and includes a
  backfill. Its reverse is a no-op apart from dropping the column.

## Permissions

Unchanged. The filter narrows querysets that are already role-scoped.

## Non-functional

- **Performance**: one extra `WHERE` clause on an existing query.
- **Migrations**: the backfill runs one `UPDATE` per academic year per quarter.
