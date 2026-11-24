---
id: 0019
slug: student-overview-api
title: Student overview, psychological-state history and paginated student sub-lists
status: in-progress
owner: almaz
created: 2026-11-24
updated: 2026-11-24
supersedes:
---

# 0019 — Student overview API, psychological-state history, paginated sub-lists

## Problem

The new-lms student detail page is being redesigned around a summary
("overview") of one student for one quarter: grades vs the class, attendance,
homework, the latest wellbeing score, and a list of things that need
attention. Today the frontend would have to assemble that from
`GET /students/{id}/` plus several analytics endpoints, and nothing computes
the "needs attention" flags.

Three more gaps:

- Psychological states only come embedded in `GET /students/{id}/` as
  `{current, history}`, and `history` holds every record ever written for the
  student. There is no paginated or filterable list.
- `students/{pk}/achievements/` and `students/{pk}/reading-entries/` return
  bare, unpaginated arrays.
- `students/{id}/reports/` is paginated by the global default (50 per page)
  but ignores `page_size`.

The frontend contract was written in the new-lms session and the frontend is
already being built against it. This spec adopts that contract. Where the
data cannot support a field, the deviation is stated under
*Deviations from the frontend contract*.

## Goals

- G-1 One request returns everything the overview header and attention panel
  need for a student and quarter.
- G-2 The thresholds that decide attention flags are backend settings that can
  be tuned without a code change.
- G-3 Psychological-state history is paginated and filterable by name.
- G-4 Achievements, reading entries and reports are paginated and honour
  `page` and `page_size`.

## Non-goals

- A submission model for homework, or `late`/`excused` attendance statuses.
  The overview reports what the existing data can support (see Deviations).
- Removing `psychological_states` (or its `history` key) from
  `GET /students/{id}/`. The frontend will say when that is safe, and that
  removal gets its own spec.
- Changing which roles can see psychological states. Parents can already see
  them through `GET /students/{id}/` and `parents/me/children/{pk}/`.
- Caching or precomputing the overview.
- Fixing the user-id vs Student-pk inconsistency between sibling routes. Each
  new route follows the id style of the routes it sits next to (see API
  contract).

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Can read the overview and paginated lists for any student |
| Teacher | Overview: 403. The new lists keep `can_view_student` |
| HomeroomTeacher | Overview: only for students in the class they are homeroom teacher of in the active year. The new lists keep `can_view_student` |
| Student | Overview: 403, even for their own. The new and paginated lists keep `can_view_student`, which allows self-access |
| Supervisor | Same as Admin |
| Principal | Same as Admin |
| Parent | Can read the overview and lists for their own children only |

## Definitions

- **Selected quarter (`Q`)**: the `quarter` query param (1–4). When it is
  absent, `Q` is `AcademicYear.current_quarter` for the active year. Between
  quarters (holidays) `current_quarter` is `None`. `Q` is then the last
  quarter whose end date is before today, or 1 if none has ended.
- **Student quarter average**: the mean of the student's `QuarterGrade.grade`
  (2–5) over their current offerings for that quarter. Subjects with no mark
  are skipped. This is the same rule as `compute_child_grades`. The value is
  `null` when there are no marks.
- **Class**: the student's major class group, i.e. the class group of their
  active enrollment in the active academic year.
- **Class quarter average**: the mean of the *student quarter averages* of
  every actively enrolled student in the class who has at least one mark that
  quarter. The value is `null` when nobody has one.
- **Attendance counts** use `ScheduleAttendance` for the student in quarter
  `Q` (`session__schedule__quarter = Q`). Unrecorded slots are never counted.
  - `rate` = `present / (present + absent) * 100`, rounded to 1 decimal. It is
    `null` when nothing is recorded.
  - `class_rate` is the same calculation pooled over the class's students.
- **Absence streak**: the student's recorded attendance days in `Q`, in date
  order. A day counts as absent when every recorded slot that day is
  `absent`. The streak is the run of absent days ending at the most recent
  recorded day. Days with no records neither extend nor break it.
- **Homework**: homework counts cover the student's current offerings,
  `Homework.is_active`, and `Homework.quarter = Q`. Legacy rows with a null
  `quarter` are excluded. There is no submission concept, so:
  - *submitted* means the student has a `HomeworkGrade` with a non-null
    `grade`.
  - *overdue* means not submitted and `due_date < today`.
  - *pending* means not submitted and (`due_date >= today` or no
    `due_date`).
  - `total` is the sum of the three.
- **Latest wellbeing**: the student's newest non-deleted
  `PsychologicalState` by `time_added`, across all names.

## Acceptance criteria

### Overview — shape and defaults

- **AC-1** — Given a student with quarter grades, when staff
  `GET /api/v1/students/{user_id}/overview/?quarter=2`, then the response is
  200 with exactly the keys `student_id, quarter, grades, attendance,
  homework, wellbeing, attention`, and `quarter == 2`.
- **AC-2** — Given no `quarter` param and today inside Q3's dates, then
  `quarter == 3`. Given today between Q2's end and Q3's start, then
  `quarter == 2`.
- **AC-3** — Given `quarter=5` or `quarter=abc`, then the response is 400.
- **AC-4** — Given a student with no grades, attendance, homework or
  psychological states, then the response is 200: every average and rate is
  `null`, every count is `0`, `wellbeing.latest` is `null`, and `attention`
  is `[]`.

### Overview — grades

- **AC-5** — `grades.average` equals the student quarter average for `Q`.
  `grades.class_average` equals the class quarter average for `Q`.
- **AC-6** — `grades.previous_quarter_average` is the student quarter average
  for `Q-1`, and is `null` when `Q == 1`.
- **AC-7** — `grades.by_quarter` always has 4 entries, ordered by quarter 1–4.
  Each entry has `{quarter, average, class_average}`, and quarters without
  marks give `null`.
- **AC-8** — The class average excludes students who are not actively enrolled
  in the class, even when they have `QuarterGrade` rows on its offerings.

### Overview — attendance, homework, wellbeing

- **AC-9** — `attendance.present`, `absent` and `total` count the student's
  recorded slots in `Q`, and `late == 0` always. `rate` and `class_rate`
  follow the Definitions above.
- **AC-10** — Homework counts follow the Definitions above. A graded homework
  past its due date counts as `submitted`, not `overdue`.
- **AC-11** — `wellbeing.latest` is `{name, score, time_added}` of the newest
  psychological state. Soft-deleted states are ignored.

### Overview — attention

- **AC-12** — A subject whose quarter grade in `Q` is ≤ `low_grade.critical`
  (default 2) yields
  `{code: "low_grade", severity: "critical", subject_id, subject_name,
  params: {grade}}`.
- **AC-13** — A subject whose grade in `Q` is at least `falling_grade.warning`
  (default 1) lower than in `Q-1` yields
  `falling_grade / warning / params {from, to}`. It never fires for `Q == 1`.
- **AC-14** — An absence streak ≥ `absence_streak.warning` (default 3) yields
  `warning`, and ≥ `absence_streak.critical` (default 5) yields `critical`,
  with `params {days}`. The flag has a null subject.
- **AC-15** — An attendance `rate` below `low_attendance.warning` (default 85)
  yields `warning`, and below `low_attendance.critical` (default 70) yields
  `critical`, with `params {rate}`. A `null` rate yields no flag.
- **AC-16** — An overdue count ≥ `overdue_homework.warning` (default 3)
  yields `warning`, with `params {count}`.
- **AC-17** — A latest wellbeing score ≤ `wellbeing_drop.warning` (default 2)
  yields `warning`, with `params {score, name}`.
- **AC-18** — `attention` is sorted with `critical` before `warning`, then
  by `code`, then by `subject_name`.
- **AC-19** — Overriding `settings.STUDENT_ATTENTION_THRESHOLDS` changes when
  flags fire. A test overrides one threshold and sees the flag flip.

### Overview — permissions

- **AC-20** — Admin, Supervisor, Principal, a psychologist, and the homeroom
  teacher of the student's class in the active year all get 200.
- **AC-20a** — The student themselves gets 403 on their own overview.
- **AC-21** — A parent gets 200 for their own child and 403 for another
  student.
- **AC-22** — Another student gets 403, and an anonymous request gets 401.
- **AC-22a** — A teacher who teaches the student a subject but is not their
  homeroom teacher gets 403.
- **AC-22b** — A homeroom teacher of a *different* class, and a homeroom
  teacher of the student's class in a past (non-active) year, get 403.
- **AC-22c** — A user who is homeroom teacher of the student's class, but
  makes the request with a non-teacher active role (e.g. `X-Active-Role:
  parent` while not this student's parent), gets 403. The access checks
  follow the active-role context from spec 0016. That context has no
  separate homeroom role: active role `teacher` covers both the Teacher and
  HomeroomTeacher groups, so homeroom access is decided by the
  `HomeroomTeacherAssignment` record, not by the role.
- **AC-23** — An unknown `user_id` gets 404.

### Psychological states list

- **AC-24** — `GET /api/v1/students/{pk}/psychological-states/` returns
  `{count, next, previous, results}`. Results are newest first, and each item
  is `{id, name, score, comment, added_by, time_added}`, the same shape as the
  embedded records today.
- **AC-25** — `?name=Anxiety` returns only records with that exact name.
- **AC-26** — `page` and `page_size` are honoured, and `page_size` is capped at
  100.
- **AC-27** — Permissions match `GET /students/{id}/`: staff who can view the
  student and the student's parent get 200, an unrelated parent or teacher
  gets 403.
- **AC-28** — `GET /students/{id}/` still returns `psychological_states` with
  both `current` and `history`, unchanged.

### Pagination of existing lists

- **AC-29** — `GET students/{pk}/achievements/` returns
  `{count, next, previous, results}`, honours `page`/`page_size`, and keeps
  the `year` and `category` filters.
- **AC-30** — `GET students/{pk}/reading-entries/` does the same, keeping the
  `year` and `month` filters.
- **AC-31** — `GET students/{id}/reports/` honours `page_size`, and the order
  stays `-created_at`.
- **AC-32** — For all three lists, the default page size is 20 and the maximum
  is 100. POST on the achievement and reading-entry endpoints is unchanged.

## API contract

| Method | Path | Id is | Permission | Notes |
|---|---|---|---|---|
| GET | `/api/v1/students/{user_id}/overview/?quarter=N` | CustomUser id (like `students/{pk}/`) | `can_view_student_overview` | new |
| GET | `/api/v1/students/{pk}/psychological-states/?page=&page_size=&name=` | Student pk (like `psychological-state/` create) | `can_view_student` | new |
| GET | `/api/v1/students/{pk}/achievements/` | Student pk | unchanged | now paginated |
| GET | `/api/v1/students/{pk}/reading-entries/` | Student pk | unchanged | now paginated |
| GET | `/api/v1/students/{id}/reports/` | Student pk | unchanged | `page_size` now honoured |

**Parent access choice:** parents use the same overview URL. The
parent branch of `can_view_student_overview` admits a parent for their own
children.
There is no `/parents/me/children/{pk}/overview/`.

<details>
<summary>Overview response</summary>

```json
{
  "student_id": 412,
  "quarter": 2,
  "grades": {
    "average": 4.2,
    "class_average": 4.0,
    "previous_quarter_average": 4.5,
    "by_quarter": [
      {"quarter": 1, "average": 4.5, "class_average": 4.1},
      {"quarter": 2, "average": 4.2, "class_average": 4.0},
      {"quarter": 3, "average": null, "class_average": null},
      {"quarter": 4, "average": null, "class_average": null}
    ]
  },
  "attendance": {"rate": 82.5, "class_rate": 91.0, "present": 33, "late": 0, "absent": 7, "total": 40},
  "homework": {"overdue": 3, "pending": 2, "submitted": 10, "total": 15},
  "wellbeing": {"latest": {"name": "Mood", "score": 2, "time_added": "2026-11-20T10:15:00+05:00"}},
  "attention": [
    {"code": "low_grade", "severity": "critical", "subject_id": 7, "subject_name": "Algebra", "params": {"grade": 2}},
    {"code": "falling_grade", "severity": "warning", "subject_id": 9, "subject_name": "Physics", "params": {"from": 4, "to": 3}},
    {"code": "low_attendance", "severity": "warning", "subject_id": null, "subject_name": null, "params": {"rate": 82.5}},
    {"code": "overdue_homework", "severity": "warning", "subject_id": null, "subject_name": null, "params": {"count": 3}},
    {"code": "wellbeing_drop", "severity": "warning", "subject_id": null, "subject_name": null, "params": {"score": 2, "name": "Mood"}}
  ]
}
```

`student_id` is the CustomUser id that was requested.

</details>

## Deviations from the frontend contract

| Field | Contract | This spec | Why |
|---|---|---|---|
| `attendance.late` | count of late | always `0` | `ScheduleAttendance` only has `present`/`absent` |
| `homework.*` | overdue / pending / submitted | based on whether the student has a grade | there is no submission model, so "submitted" means "graded" |
| `wellbeing_drop.params` | `{score}` | `{score, name}` | the student has several named states, so the name says which one dropped |
| `low_grade.params` | unspecified | `{grade}` | — |

## Data model

No model changes and no migration.

- `core/settings.py` gets a `STUDENT_ATTENTION_THRESHOLDS` dict with the
  defaults above. The overview reads it with
  `getattr(settings, 'STUDENT_ATTENTION_THRESHOLDS', DEFAULTS)`.

## Permissions

1. **Route-level**: `IsAuthenticated`. This matches `StudentDetailAPIView`.
2. **Object-level**:
   - **Overview**: a new `can_view_student_overview(user, student)` in
     `core/permissions.py`. It is stricter than `can_view_student` and admits
     only:
     - an admin role (`is_admin_role`: admin, supervisor, principal);
     - a parent whose `Parent.students` contains the student;
     - a psychologist;
     - with active role `teacher`, the teacher holding a
       `HomeroomTeacherAssignment` for the student's current major class
       group in the active academic year.

     Subject teachers and the student themselves are not admitted. Every check goes through the
     active-role helpers from spec 0016. On deny it returns 403, and the
     frontend falls back quietly to the report card.
   - **Psychological states and the paginated lists**: unchanged,
     `can_view_student`. Its teacher-role check admits any teacher, the
     student, their parents and psychologists. This spec does not change who
     can read those lists.
3. **View-level**: every query is filtered to the one student, or to their
   class for the class averages. The class averages return only aggregates,
   never other students' rows.

## Non-functional

- **Performance**: the overview should take ≤ 15 queries whatever the number
  of subjects. Class averages use one aggregate query per metric, not one per
  student. A test asserts the query count.
- **Security**: class averages expose only aggregates. Parents gain no data
  they cannot already reach through `GET /students/{id}/`.
- **Compatibility**: paginating achievements and reading entries changes them
  from a bare array to an object. The new-lms frontend accepts both. Other
  consumers of these two endpoints (Django templates, scripts) must be
  checked during planning.
- **Migrations**: none.

## Open questions

- [x] Is "graded = submitted" acceptable for homework? **Yes**, answered
      2026-11-24 and relayed from the new-lms session.
- [x] Which teachers can see the overview? **Homeroom teachers of the
      student's class only.** Subject teachers get 403. Answered 2026-11-24
      and relayed from the new-lms session. See AC-20 and AC-22a–c.
- [x] Should the student see their own overview? **No** (AC-20a). Answered
      2026-11-24, relayed from new-lms.
- [x] Should the psychological states, achievements, reading entries and
      reports lists be narrowed? **No**, they keep `can_view_student`.
      Answered 2026-11-24, relayed from new-lms.
- [x] Should parents see psychological-state `comment`s in the new list?
      **Yes**, unchanged. Answered 2026-11-24, relayed from new-lms.
