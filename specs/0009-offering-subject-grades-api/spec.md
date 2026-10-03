---
id: 0009
slug: offering-subject-grades-api
title: Every assignment of an offering with its grades, in one request
status: in-progress
owner: bekzhan
created: 2026-10-01
updated: 2026-10-02
supersedes:
---

# 0009 — Every assignment of an offering with its grades, in one request

## Problem

`GET subject-assignments/<assignment_id>/grades/` returns the grades of one
assignment. A gradebook for a class shows every assignment of the subject,
so the client makes one request per assignment.

## Goals

- G-1 `GET /api/v1/offerings/<offering_id>/subject-grades/` returns the
  offering's assignments. Each one comes with its grades nested inside.
- G-2 Visibility is the same as the existing per-assignment endpoint. Nobody
  sees an assignment or a grade here that they could not already see.

## Non-goals

- Writing grades. `POST subject-assignments/<id>/grades/` and
  `PATCH/DELETE subject-grades/<pk>/` are unchanged.
- Placeholder rows for students who have no grade yet. Only stored grades are
  returned.
- Changing any existing endpoint.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin, Supervisor, Principal, Psychologist | Every assignment of the offering (drafts included), with every grade. |
| Teacher | Every assignment of an offering they teach (drafts included), with every grade. |
| HomeroomTeacher | Also the published assignments of any offering taught to their homeroom class, with the grades of that class. |
| Student | The published assignments of an offering in their class, with their own grade only. |
| Parent | The same, for their children. |
| Others | Empty list. |

## Acceptance criteria

- **AC-1** — A teacher of the offering gets 200. The result has one entry per
  assignment of the offering. Each entry carries the `SubjectAssignment` fields
  and a `grades` list of `{id, student, student_user_id, student_name, grade,
  comments, created_at}`.
- **AC-2** — Assignments of other offerings never appear.
- **AC-3** — A student gets only published assignments, and only their own
  grade in each one. A parent gets only their children's grades.
- **AC-4** — A teacher who neither teaches the offering nor is homeroom
  teacher of its class gets an empty list.
- **AC-5** — The homeroom teacher of the offering's class gets its published
  assignments with their class's grades, even without teaching the subject.
- **AC-6** — `category`, `date`, `date_from` and `date_to` filter the
  assignments, with the same meaning as on `GET subject-assignments/`.
- **AC-7** — Assignments are ordered newest first (`-date, -created_at, -id`).
  Grades within an assignment are ordered by student last name, then first
  name. The list is paginated over assignments, with `page` and `page_size`.
- **AC-8** — An offering that does not exist, or belongs to another school,
  returns 404. An anonymous caller gets 401.
- **AC-9** — The number of queries does not grow with the number of
  assignments or grades.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/offerings/<offering_id>/subject-grades/` | Authenticated, role-scoped | Filters: `category`, `date`, `date_from`, `date_to`, `page`, `page_size` |

<details>
<summary>Response</summary>

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [{
    "id": 12, "title": "Quiz 3", "category": "lesson", "category_name": "Lesson",
    "max_grade": 10, "date": "2026-09-28", "detail_id": null, "is_active": true,
    "offering_id": 7, "subject_id": 3, "subject_name": "Mathematics",
    "class_group_id": 9, "class_group_name": "7A", "academic_year_id": 2,
    "created_at": "…",
    "grades": [{
      "id": 501, "student": 15, "student_user_id": 40,
      "student_name": "…", "grade": 8, "comments": "…", "created_at": "…"
    }]
  }]
}
```

</details>

`max_grade` is null on a comment-only assignment (spec 0005, AC-26). Its
nested `grades` then carry `comments` and always `"grade": null`.

## Data model

No change.

## Permissions

1. **Route-level**: `IsAuthenticated`.
2. **Object-level**: none. The offering is looked up through the
   school-scoped manager, so another school's offering is a 404.
3. **View-level**: assignments come from `assignment_queryset(user)`, widened
   with `homeroom_assignment_queryset(user)`. Grades come from
   `grade_queryset(user)`. These are the same querysets the existing
   endpoints use.

## Non-functional

- **Performance**: grades are loaded with `prefetch_related`, so the query
  count is fixed whatever the page size.
- **Security**: no new data is exposed. Every row was already visible through
  an existing endpoint.
- **Migrations**: none.
