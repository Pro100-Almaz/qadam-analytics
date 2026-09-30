---
id: 0007
slug: homework-assignment-delete-one-way
title: Homework assignments are deleted through the Homework only
status: shipped
owner: bekzhan
created: 2026-09-30
updated: 2026-09-30
supersedes: 0005
---

# 0007 — Homework assignments are deleted through the Homework only

> Supersedes **only AC-18** of spec 0005, "`DELETE subject-assignments/<pk>/`
> on a homework assignment deletes the `Homework`…". Every other part of
> 0005 stands.

## Problem

Under 0005, deleting a `homework`-category `SubjectAssignment` also deletes the
`Homework` behind it, including its grades and stored attachment files. The
subject-assignment list is where teachers work with every kind of graded work,
so one click there can wipe out a homework task and everything attached to it.
The Homework is the primary record. Only its own endpoint should be able to delete it.

## Goals

- G-1 Deletion flows one way only: deleting a `Homework` deletes its
  `SubjectAssignment` (unchanged from 0005). Deleting a homework
  `SubjectAssignment` directly is refused.

## Non-goals

- Changing Homework deletion (`DELETE homeworks/<pk>/`, admin, `TeachingAssignment.delete`). It still takes the mirror with it.
- Changing grade sync. Deleting a `SubjectGrade` on a homework assignment still
  deletes the matching `HomeworkGrade`, and the reverse holds too (0005 AC-19).
- Changing deletion of assignments in any other category.
- Changing create, update or category rules from 0005.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Teacher | `DELETE subject-assignments/<pk>/` on a homework assignment → 400. They delete it through `DELETE homeworks/<detail_id>/` instead. |
| Others | None. Admin roles cannot write assignments anyway. |

## Acceptance criteria

- **AC-1** — `DELETE /api/v1/subject-assignments/<pk>/` on a `homework`
  assignment returns **400**, with a message naming
  `DELETE /api/v1/homeworks/<detail_id>/`. The assignment, the Homework, both
  sides' grades and the attachment files all still exist afterwards.
- **AC-2** — `SubjectAssignment.delete()` on a `homework` assignment whose
  Homework exists raises `ValidationError`, and nothing is deleted. This blocks
  code paths other than the API too.
- **AC-3** — `DELETE /api/v1/homeworks/<pk>/` still deletes the mirrored
  assignment and its grades (0005 AC-15 unchanged).
- **AC-4** — A `homework` assignment whose Homework is already gone (an orphan,
  e.g. after a raw delete) can still be removed by
  `sync_homework_assignments --fix` (0005 AC-22 unchanged).
- **AC-5** — `DELETE subject-assignments/<pk>/` on a non-homework assignment
  still returns 204 and deletes it with its grades.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| DELETE | `/api/v1/subject-assignments/<pk>/` | Teacher of offering | Category `homework` → `400 {"detail": "…delete the homework instead: DELETE /api/v1/homeworks/<detail_id>/"}`. Other categories unchanged (204). |

The permission check runs first: a teacher of another offering still gets 403.

## Data model

No schema change. `SubjectAssignment.delete()` refuses a homework assignment
whose Homework exists. The internal `sync=False` path that `Homework.delete()`
and the sync command use is unaffected.

## Permissions

Unchanged at all three tiers.

## Non-functional

- **Migrations** — none.
