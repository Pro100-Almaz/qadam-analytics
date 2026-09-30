---
id: 0005
slug: dynamic-assignment-categories
title: Admin-managed SubjectAssignment categories, with Homework mirrored as a category
status: shipped
owner: bekzhan
created: 2026-09-30
updated: 2026-09-30
---

# 0005 — Dynamic assignment categories and the Homework mirror

## Problem

`SubjectAssignment.category` (`apps/home/models.py:688`) is a CharField with
hard-coded `CATEGORY_CHOICES` = `lesson`, `exam`, `final`. Adding a kind of
graded work needs a code change and a deploy. The same three values are frozen
into the API serializers (`apps/home/api/serializers.py:817,839`), the OpenAPI
enum (`apps/home/api/views/assignments.py:310`) and the analytics breakdown
(`apps/lesson/api/analytics_subject.py:104`).

Homework is graded work too, but it lives in its own model, `lesson.Homework`
and `lesson.HomeworkGrade`, and nothing links it to `SubjectAssignment`. So
homework marks are missing from subject analytics, grade sheets
(`apps/student_report/services/grade_sheet.py`) and `GET subject-grades/`.

## Goals

- G-1 Admins add and delete assignment categories in `/admin/` without a deploy.
- G-2 A new `homework` category exists, and every `Homework` has exactly one
  `SubjectAssignment` of that category. Its grades are mirrored, so homework
  appears everywhere subject assignments do.
- G-3 The two sides stay in sync on create, update and delete, from either
  side, without Django signals.
- G-4 A generic "detail" pointer (`detail_id`) lets future categories get their
  own detail model the same way.

## Non-goals

- Per-school categories. A category is global: one admin adding it makes it
  visible to every school.
- Detail models for `lesson`, `exam`, `final` or any category other than `homework`.
- Syncing homework attachments into `SubjectAssignment`. Files stay on `Homework`.
- Changing who may read or write homework or assignments (the 3-tier rules stay as they are).
- Changing grade calculation or weighting by category.
- A frontend change. The API keeps sending `category` as its string code.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Manages `AssignmentCategory` in `/admin/`. Sees homework in subject-assignment lists and analytics. |
| Teacher | Can create homework through `POST subject-assignments/` with `category=homework`. Homework and its grades appear in subject-assignment and grade lists. |
| HomeroomTeacher | Published homework appears in `my-class/subject-assignments/`. Drafts do not. |
| Student | Published homework and its grades appear in subject grades and analytics. Drafts do not. |
| Supervisor / Principal | Same as Admin for reading. |
| Parent | Same as Student, for their children. |

## Acceptance criteria

Categories:

- **AC-1** — Given an admin adds a category `project` in `/admin/`, then
  `GET /api/v1/assignment-categories/` lists it for users of **every** school,
  and `POST subject-assignments/` accepts `category=project`.
- **AC-2** — Given a category has at least one assignment, when an admin tries
  to delete it, then the delete is refused (`on_delete=PROTECT`) and the row stays.
- **AC-3** — The `homework` category cannot be deleted from `/admin/`, even when
  it has no assignments, and its `code` cannot be edited.
- **AC-4** — Existing assignments keep their category through the migration.
  A row with `lesson`, `exam` or `final` before has the category with the same code after.
- **AC-5** — The `category` value in API responses is still the string code,
  and filtering `?category=exam` still works on the subject-assignments list and analytics.

`detail_id` checks:

- **AC-6** — Saving a `homework` assignment without `detail_id` raises `ValidationError`.
- **AC-7** — Saving a `homework` assignment whose `detail_id` points to no `Homework` raises `ValidationError`.
- **AC-8** — Saving a `homework` assignment whose `Homework` belongs to a
  different offering raises `ValidationError`.
- **AC-9** — Saving a non-homework assignment with a `detail_id` raises `ValidationError`.
- **AC-10** — Two assignments with the same `(category, detail_id)` are refused by a DB constraint.
- **AC-11** — Changing an existing assignment's category into or out of
  `homework` is refused, by the model and by `PATCH subject-assignments/<pk>/` (400).

Sync:

- **AC-12** — Migration backfill: every `Homework` present before the migration
  has one `homework` assignment with `title=description`, `max_grade`,
  `date=due_date`, `offering` and `is_active` copied. Every `HomeworkGrade` has
  a `SubjectGrade` with the same `grade` and `comments`.
- **AC-13** — `POST /api/v1/homeworks/` with N offerings creates N mirrored assignments.
- **AC-14** — `PUT /api/v1/homeworks/<pk>/` changing description, max_grade,
  due_date or is_active updates the mirrored assignment to match.
- **AC-15** — `DELETE /api/v1/homeworks/<pk>/` deletes the mirrored assignment and its grades.
- **AC-16** — `POST subject-assignments/` with `category=homework` creates a
  `Homework` on the caller's teaching assignment and links it through `detail_id`.
  `max_grade > 100` gives a 400.
- **AC-17** — `PATCH subject-assignments/<pk>/` on a homework assignment updates the `Homework`.
- **AC-18** — `DELETE subject-assignments/<pk>/` on a homework assignment
  deletes the `Homework`, its grades and its stored attachment files.
- **AC-19** — Creating, changing or deleting a `HomeworkGrade` does the same to
  the matching `SubjectGrade`, and the reverse holds too.
- **AC-20** — Saving through `/admin/` (Homework change form) syncs the same way as the API.
- **AC-21** — Deleting a `TeachingAssignment` that owns homework leaves no
  `homework` assignment pointing at a deleted `Homework`.
- **AC-22** — `python manage.py sync_homework_assignments --check` exits 0 when
  both sides agree. It exits non-zero and lists the rows when a mirror is
  missing, orphaned or has drifted. `--fix` repairs them.

Drafts:

- **AC-23** — A draft homework (`is_active=False`) has an assignment with
  `is_active=False`. Students, parents and homeroom lists, subject analytics and
  grade sheets exclude it. The offering's teachers and admin roles still see it.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/assignment-categories/` | Authenticated | New. `[{"id", "code", "name"}]`, ordered by name. |
| GET | `/api/v1/subject-assignments/` | unchanged | Adds `category_name`, `detail_id`, `is_active` to each row. `category` is still the code. |
| POST | `/api/v1/subject-assignments/` | Teacher of offering | `category` accepts any existing code (default `lesson`). `homework` also creates a `Homework`. Optional `is_active` (default true). |
| PATCH | `/api/v1/subject-assignments/<pk>/` | Teacher of offering | Category change into or out of `homework` → 400. |
| * | `/api/v1/homeworks/…`, `/api/v1/homework-grades/…` | unchanged | Unchanged, but writes now update the mirror. |

## Data model

- `apps/home/models.py`
  - New `AssignmentCategory(code: slug unique, name, created_at)`. Shared, not
    school-scoped, so it goes in `core.checks.SHARED_MODELS`.
  - `SubjectAssignment.category` → `ForeignKey(AssignmentCategory, on_delete=PROTECT)`.
  - New `SubjectAssignment.detail_id = PositiveIntegerField(null=True)`: the pk
    of the category's detail model row. Only `homework` → `lesson.Homework` has one today.
  - New `SubjectAssignment.is_active = BooleanField(default=True)`.
  - `UniqueConstraint(category, detail_id) WHERE detail_id IS NOT NULL`.
- Migrations: `home` adds the table, seeds four categories, converts the
  column (data-preserving) and adds the new columns. `lesson` backfills the mirrors.
  Both are reversible.

## Permissions

1. **Route-level** — unchanged. The new categories endpoint is `IsAuthenticated`.
2. **Object-level** — unchanged. Creating homework through subject-assignments
   uses the same `teacher_assignment_for` check as today.
3. **View-level** — student, parent and homeroom assignment/grade querysets also filter `is_active=True`.

## Non-functional

- **Performance** — sync adds one extra write per homework or grade write.
  Bulk homework create syncs in bulk. List endpoints add `select_related('category')`.
- **Security** — drafts must not leak through the new mirror (AC-23).
- **Migrations** — reversible, with no downtime needed. Backfill size is
  bounded by the current Homework and HomeworkGrade counts.
- **Consistency** — Sync runs in model `save()`/`delete()` and inside
  transactions, not in signals. Paths that skip them (`bulk_create`,
  `QuerySet.update/delete`) are covered explicitly where the code uses them, and
  the `sync_homework_assignments` command is the safety net.

## Open questions

- [x] Grades sync too? — Yes.
- [x] Homework-category assignment created via subject-assignments API? — Auto-create the Homework.
- [x] Drafts? — Mirrored, with an `is_active` flag on the assignment.
