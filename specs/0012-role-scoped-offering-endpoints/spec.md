---
id: 0012
slug: role-scoped-offering-endpoints
title: Role-scoped offering endpoints for teachers and homeroom teachers
status: in-progress
owner: bekzhan
created: 2026-10-05
updated: 2026-10-05
supersedes: 0010
---

# 0012 — Role-scoped offering endpoints for teachers and homeroom teachers

> Supersedes **only AC-2** of spec 0010, which describes the rows of
> `analytics/assignment-offerings/`. That endpoint is removed here. Every
> other part of 0010 stands. It also moves `GET /api/v1/teacher/my-class/`
> described in spec 0002 to a new path.

## Problem

`GET /api/v1/analytics/assignment-offerings/` mixes two roles. For a teacher
who is also a homeroom teacher, it returns the offerings they teach plus
every offering of their homeroom class, flagged with `access`. The frontend
wants one endpoint per role, where each one returns only what that role
covers.

The homeroom class overview lives at `GET /api/v1/teacher/my-class/`. That
is under the teacher prefix even though it is a homeroom-only screen. Its
payload also has no list of the class's offerings, only subject names
nested under each student.

## Goals

- G-1 `GET /api/v1/teacher/offerings/` returns only the offerings the caller
  teaches (has a `TeachingAssignment` on), whatever other roles they hold.
- G-2 `GET /api/v1/homeroom/my-class/` replaces `teacher/my-class/` and
  returns the homeroom class, its students and the class's offerings.
- G-3 Remove `GET /api/v1/analytics/assignment-offerings/`.

## Non-goals

- Admins inspecting another teacher's offerings. The old `teacher` query
  param is not carried over. Each endpoint answers for the caller only.
- Any change to the trajectory or summary analytics, or to
  `teacher/my-classes/`, `teacher/dashboard/` or `teaching-assignments/`.
- Changes to how `students[].subjects` grades are computed on the homeroom
  payload.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Teacher, HomeroomTeacher | New `teacher/offerings/`. `analytics/assignment-offerings/` returns 404. |
| HomeroomTeacher | `teacher/my-class/` moves to `homeroom/my-class/` and gains `offerings`. |
| Admin, Supervisor, Principal (without the role) | Get 403 from both endpoints. Before, admins could use `teacher/my-class/` and the `teacher` param. |

## Acceptance criteria

- **AC-1** — `GET /api/v1/teacher/offerings/` lists exactly the offerings
  the caller has a `TeachingAssignment` on, in the requested academic year
  (default: the active one), for active subjects, each listed once.
- **AC-2** — A teacher who is also a homeroom teacher does not get the
  offerings of their homeroom class that they do not teach.
- **AC-3** — `include_empty=false` drops offerings with no subject
  assignment. The default is `true`.
- **AC-4** — Each row carries `teaching_role` and no `access` or
  `is_homeroom_class` key.
- **AC-5** — `teacher/offerings/` is 403 for a user outside the Teacher and
  HomeroomTeacher groups, including an Admin.
- **AC-6** — `GET /api/v1/homeroom/my-class/` returns the caller's homeroom
  class, its active students and an `offerings` list of every offering of
  that class with its teachers.
- **AC-7** — `homeroom/my-class/` is 403 for a user outside the
  HomeroomTeacher group, including an Admin. It is 404 for a homeroom
  teacher with no class this year.
- **AC-8** — Neither `/api/v1/teacher/my-class/` nor
  `/api/v1/analytics/assignment-offerings/` resolves.

## API contract

| Method | Path | Change |
|---|---|---|
| GET | `/api/v1/teacher/offerings/` | New. Params: `academic_year`, `include_empty` |
| GET | `/api/v1/homeroom/my-class/` | New path for `teacher/my-class/`, plus `offerings` and `students[].subjects[].offering_id` |
| GET | `/api/v1/teacher/my-class/` | Removed |
| GET | `/api/v1/analytics/assignment-offerings/` | Removed |

## Data model

No change.

## Permissions

- `teacher/offerings/`: `IsTeacherRole` (Teacher or HomeroomTeacher group).
  There is no admin bypass.
- `homeroom/my-class/`: `IsHomeroomTeacher`. There is no admin bypass.

## Non-functional

- **Migrations**: none.
