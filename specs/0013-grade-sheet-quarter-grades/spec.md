---
id: 0013
slug: grade-sheet-quarter-grades
title: Quarter grades in the XLSX grade sheets
status: in-progress
owner: bekzhan
created: 2026-10-22
updated: 2026-10-22
supersedes:
---

# 0013 — Quarter grades in the XLSX grade sheets

> Partly reverses a non-goal of spec 0008 ("Read access for students and
> parents"). Here, students and parents get read access to quarter grades,
> but **only through the XLSX grade sheets**. Every method of
> `offerings/<id>/quarter-grades/` stays 403 for them, as 0008 AC-3 says.

## Problem

`GET /api/v1/grade/classgroup/<id>/` and `GET /api/v1/grade/student/<id>/`
export a quarter's `SubjectAssignment` grades as an `.xlsx` workbook. The
quarter grade a teacher gives for each offering (`QuarterGrade`, 2–5) does not
appear anywhere in that file. To see the final mark next to the assignment
grades it came from, someone has to look it up separately. There is also no
single view of every subject's quarter grade for a class.

## Goals

- G-1 Every assignment table in the workbook ends with a **Quarter Grade**
  column. It shows the student's `QuarterGrade` for that offering and
  quarter.
- G-2 When no `subject` filter is given, the workbook opens on a **Quarter
  Grades** sheet: students are the rows, subjects are the columns, and each
  cell is that student's quarter grade.

## Non-goals

- Computing or suggesting a quarter grade from assignment grades. The sheet
  only shows `QuarterGrade` rows that exist.
- Any change to the `offerings/<id>/quarter-grades/` API or its permissions
  (spec 0008).
- Any change to who may download a grade sheet.
- Year or semester grades. The sheet covers one quarter, as it does today.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin, Supervisor, Principal | See quarter grades in both sheets. |
| HomeroomTeacher | Sees quarter grades for every subject of their class. |
| Teacher | With `?subject=`, sees the Quarter Grade column for that subject. Never gets the summary sheet, because their access always needs `subject`. |
| Student | Sees their own quarter grades in `grade/student/<own id>/`. **New read access.** |
| Parent | Sees their children's quarter grades in `grade/student/<child id>/`. **New read access.** |

## Acceptance criteria

- **AC-1** — In `ordering=subject` (the default), every subject sheet's
  last column is headed `Quarter Grade`. In each student's row, it holds
  that student's `QuarterGrade.grade` for the sheet's offering and the
  requested quarter.
- **AC-2** — In `ordering=student`, every subject table on a student's
  sheet ends with a `Quarter Grade` column. It holds that student's quarter
  grade for that offering and quarter.
- **AC-3** — When no `QuarterGrade` row exists for the student, offering
  and quarter, the Quarter Grade cell is empty (no value, not `-`).
- **AC-4** — Quarter grades from another quarter, or from an offering
  outside the sheet, never appear.
- **AC-5** — A subject with no assignments in the quarter still lists its
  students (`subject` ordering) or its table (`student` ordering), with the
  Quarter Grade column filled in.
- **AC-6** — Without `subject`, the first sheet of the workbook is named
  `Quarter Grades`. This holds for both orderings and both endpoints. Rows
  are the sheet's students, in the same order as elsewhere. Columns are
  the class group's offerings, ordered by subject name. Each cell is the
  student's quarter grade for that offering and quarter, or empty if there
  is none.
- **AC-7** — With `subject`, the workbook has no `Quarter Grades` sheet.
- **AC-8** — If a subject is itself named "Quarter Grades", the summary
  sheet keeps that exact name and the subject sheet gets a suffix.
- **AC-9** — A student or parent who may download `grade/student/<id>/`
  sees that student's quarter grades in it.
- **AC-10** — Building the workbook adds exactly one query for quarter
  grades, however many students or subjects there are.

## API contract

No change to paths, parameters, permissions or status codes. Only the
contents of the `.xlsx` change.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/grade/classgroup/<id>/` | unchanged | gains Quarter Grade column + summary sheet |
| GET | `/api/v1/grade/student/<id>/` | unchanged | gains Quarter Grade column + summary sheet |

## Data model

No change. Reads `apps/home/models.py` → `QuarterGrade`
(`unique_together = student, offering, quarter`), so each cell has at most
one value.

## Permissions

1. **Route-level** — unchanged (`IsAuthenticated`).
2. **Object-level** — unchanged (`apps/student_report/permissions.py`).
   Whoever can read the sheet can read the quarter grades in it.
3. **View-level** — quarter grades are limited to the sheet's offerings,
   students and quarter, exactly as assignment grades are.

## Non-functional

- **Performance** — one extra query
  (`QuarterGrade` filtered by offering in, student in, quarter).
- **Security** — students and parents gain read access to their own or
  their child's quarter grades through the sheet. This is a deliberate
  decision made on 2026-10-22. See the note at the top.
- **Migrations** — none.

## Open questions

- [x] Students/parents see quarter grades in the sheet? Yes (decided
  2026-10-22).
- [x] Summary sheet position? First.
