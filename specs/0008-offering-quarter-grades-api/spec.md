---
id: 0008
slug: offering-quarter-grades-api
title: Quarter grades are managed per offering, in bulk
status: in-progress
owner: bekzhan
created: 2026-10-01
updated: 2026-10-01
supersedes:
---

# 0008 — Quarter grades are managed per offering, in bulk

## Problem

Quarter grades are served from a flat `/api/v1/quarter-grades/` resource that
writes one row per request. A teacher who finishes a quarter for a class of 30
has to make 30 POSTs. The list is also readable by students and parents, but
quarter grades should only be visible to staff.

## Goals

- G-1 Quarter grades are addressed through their offering:
  `/api/v1/offerings/<offering_id>/quarter-grades/`.
- G-2 A whole quarter for a class is written in one request: a quarter plus a
  `{student_id: grade}` dict. The write is all-or-nothing.
- G-3 Any staff member can read. Only a teacher of the offering can write.

## Non-goals

- Deriving quarter grades from assignment grades. They are still entered by hand.
- Writes by admin roles, through the API or the Django admin. `QuarterGrade`
  stays unregistered in the admin.
- Writes by a homeroom teacher who does not teach the offering.
- Read access for students and parents. A separate spec can add that later.
- Changing `GET /api/v1/teachers/my-class/quarter-grades/`, the homeroom read
  endpoint. It stays as it is.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin, Supervisor, Principal | Can read any offering's quarter grades. Writes → 403 (no change). |
| Psychologist | Can read any offering's quarter grades. |
| Teacher | Can read any offering's quarter grades. Writes only to offerings they have a `TeachingAssignment` on. |
| HomeroomTeacher | Same as Teacher. Their homeroom class gives them no write access. |
| Student, Parent | Lose read access. Everything → 403. |
| ClubManager | No access, 403. Not a staff role. |

"Staff" means `IsStaffOrAdmin`: Admin, Supervisor, Principal, Teacher,
HomeroomTeacher or Psychologist.

## Acceptance criteria

- **AC-1** — Staff can GET `offerings/<id>/quarter-grades/` for any offering
  in the school, including one they do not teach. They get 200 and every
  quarter grade of that offering.
- **AC-2** — `?quarter=N` limits the GET to that quarter.
- **AC-3** — Student, parent and club-manager callers get 403 on every method.
  Anonymous callers get 401.
- **AC-4** — A teacher of the offering POSTs `{"quarter": q, "grades": {sid:
  g, …}}` and gets 201. One row is created per student, and the created rows
  are returned.
- **AC-5** — POST, PATCH and DELETE return 403 and change nothing when the
  caller is an admin role, a teacher of another offering, or the homeroom
  teacher of the offering's class who does not teach it.
- **AC-6** — POST returns 400 and creates nothing if any student in the
  payload already has a grade for that quarter in this offering.
- **AC-7** — POST and PATCH return 400 and write nothing if any student is not
  actively enrolled in the offering's class group, or if any grade is outside
  2–5. The 400 names the offending student ids.
- **AC-8** — PATCH with the same payload shape changes the grades of the
  listed students and returns 200 with the updated rows. Students not listed
  are untouched. If any listed student has no grade for that quarter, it
  returns 400 and changes nothing.
- **AC-9** — DELETE with `{"quarter": q, "students": [sid, …]}` deletes those
  rows and returns 204. If any listed student has no grade for that quarter, it
  returns 400 and deletes nothing.
- **AC-10** — An offering id that does not exist, or belongs to another
  school, returns 404.
- **AC-11** — The old `/api/v1/quarter-grades/` and
  `/api/v1/quarter-grades/<pk>/` routes no longer resolve.
- **AC-12** — `QuarterGrade` is not registered in the Django admin.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/offerings/<offering_id>/quarter-grades/` | Staff | Optional `?quarter=1..4`. Unpaginated list. |
| POST | `/api/v1/offerings/<offering_id>/quarter-grades/` | Teacher of the offering | Creates rows, all-or-nothing. |
| PATCH | `/api/v1/offerings/<offering_id>/quarter-grades/` | Teacher of the offering | Updates rows, all-or-nothing. |
| DELETE | `/api/v1/offerings/<offering_id>/quarter-grades/` | Teacher of the offering | Deletes rows, all-or-nothing. |
| — | `/api/v1/quarter-grades/`, `/api/v1/quarter-grades/<pk>/` | — | Removed. |

The permission check runs before payload validation. A caller without write
access gets 403 whatever the body contains.

<details>
<summary>Request / response shapes</summary>

POST / PATCH request. Keys are `Student` profile ids. JSON object keys are
strings and get parsed as integers.

```json
{"quarter": 2, "grades": {"15": 4, "16": 5}}
```

DELETE request:

```json
{"quarter": 2, "students": [15, 16]}
```

GET / POST / PATCH response, a list of:

```json
{
  "id": 1, "quarter": 2, "grade": 4,
  "student": 15, "student_user_id": 40, "student_name": "…",
  "offering_id": 7, "subject_id": 3, "subject_name": "Mathematics",
  "class_group_id": 9, "class_group_name": "7A",
  "academic_year_id": 2, "created_at": "…"
}
```

400 example:

```json
{"grades": {"17": ["This student is not enrolled in the class group of this offering."]}}
```

</details>

## Data model

No schema change. `QuarterGrade` keeps `unique_together = (student, offering, quarter)`.

## Permissions

1. **Route-level**: GET uses `IsStaffOrAdmin`. Writes use `IsTeacherRole`.
2. **Object-level**: writes need the caller's own `TeachingAssignment` on the
   offering (`teacher_assignment_for`). Admin roles get no bypass for writes.
3. **View-level**: the offering is looked up through the school-scoped
   manager, so another school's offering is a 404.

## Non-functional

- **Performance**: enrollment and existing-row checks run as one query each,
  whatever the class size. Creates go through `save()` one row at a time,
  inside one transaction. `bulk_create` would skip
  `SchoolConsistentModel.save()` and its cross-school check. A class is about
  30 rows. Updates change only `grade`, so they use `bulk_update`.
- **Security**: students and parents lose read access (intended, G-3).
- **Migrations**: none.
