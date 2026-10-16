---
id: 0013
slug: soft-delete
title: Soft deletion with restore and an admin trash
status: shipped
owner: bekzhan
created: 2026-10-14
updated: 2026-10-15
supersedes: 0005
---

# 0013 — Soft deletion with restore and an admin trash

> Supersedes **only** the following parts of spec 0005. Everything else in
> 0005, and all of 0007, stands.
>
> - Deleting a `Homework` removes its stored attachment files. Files are now
>   removed only when the homework is purged from the trash.
> - Deleting a `TeachingAssignment` deletes its homeworks. Its homeworks now
>   survive, and `Homework.teaching_assignment` becomes `SET_NULL`.

## Problem

Every delete in the domain models is a hard delete, and Postgres cascades it.
Deleting one `SubjectOffering` removes its lessons, topics, topic grades,
assignments, grades and homeworks for good. Deleting a user removes their
profile and every grade that hangs off it. Nothing can be recovered short of a
database restore.

Only `Lesson` and the achievement models use the existing `SoftDeleteMixin`
(`core/models.py`). Even there, it works on one row at a time. It does not
cascade, `delete()` still hard-deletes, there is no batch restore, and unique
constraints still count deleted rows. That last point means that once `A.b` is
soft-deleted, no live row can take the value `b`.

Two more things are wrong today:

- `Homework.teaching_assignment` is `CASCADE`. Removing a teacher from an
  offering wipes that teacher's homework, along with the grades and files
  attached to it.
- Admins have no place to see what was deleted or to bring it back.

## Goals

- G-1: `delete()`, `QuerySet.delete()` and admin deletion on the models in
  scope set `is_deleted=True` instead of removing rows. The delete cascades
  along the same `CASCADE` edges a hard delete would follow.
- G-2: All default reads (`Model.objects`, reverse relations, the admin
  changelist) return live rows only.
- G-3: A deleted row and everything deleted together with it can be restored
  in one action.
- G-4: Uniqueness applies to live rows only. A deleted row never blocks a new
  row with the same value.
- G-5: An admin trash page in Django `/admin/` lists deleted rows, restores
  them, and lets an admin purge them for good.
- G-6: `Homework.teaching_assignment` is `SET_NULL`.

## Non-goals

- Soft deletion of `QuarterGradeSnapshot`. Snapshots are immutable, and `save()`
  raises on any update.
- Soft deletion of `Attachment`. Attachments stay with their parent and are
  removed only when the parent is purged.
- Soft deletion of shared lookup tables: `GradeLevel`, `AssignmentCategory`,
  `SchoolGroup` and `PsychologicalStateTemplates`.
- Soft deletion of M2M through rows. They stay untouched and come back
  unchanged on restore.
- A trash UI outside Django `/admin/` (for example, in the frontend app).
- Automatic purging of old trash, such as a retention period.
- Writing `simple_history` records for soft deletes. Soft delete stamps rows
  with `update()`, which skips the history hooks.
- Soft deletion of `School`. A school is hard-deleted only, and only directly
  in the database. Neither the admin nor any API offers a way to delete one
  (AC-15).
- Cascading along `SET_NULL` edges. For example, deleting an `AcademicYear`
  does not delete its `ClassGroup`s, because `ClassGroup.academic_year` is
  `SET_NULL`.

## Scope: models that become soft-deletable

| App | Models |
|---|---|
| authentication | `CustomUser`, `Student`, `Teacher`, `Parent`, `Supervisor`, `ClubManager`, `PsychologicalState` |
| home | `AcademicYear`, `ClassGroup` (with the proxy `MinorClassGroup`), `ClassGroupCollection`, `Subject`, `SubjectOffering`, `TeachingAssignment`, `HomeroomTeacherAssignment`, `Enrollment`, `QuarterGrader`, `SubjectAssignment`, `SubjectGrade`, `QuarterGrade` |
| lesson | `Lesson` (already soft-deletable), `Topic`, `TopicGrade`, `MergedLessonComment`, `SubjectSchedule`, `ScheduleSession`, `ScheduleAttendance`, `Homework`, `HomeworkGrade` |
| student_report | `StudentReport` |
| notification | `Notification` |
| achievement | Already soft-deletable. These models gain the cascade and batch behaviour. |

The rule behind the list: any model that a soft-deletable model reaches by a
`CASCADE` edge must itself be soft-deletable. A system check enforces this
(AC-12).

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Superuser | Can no longer delete a `School` in `/admin/`, even an empty one. Deleting a school is done directly in the database. |
| Admin | Deletes in `/admin/` become recoverable. A new **Trash** page offers restore and purge. Only Admin and superusers may purge. |
| Teacher | Deletes through the API become recoverable by an admin. Removing a teacher from an offering no longer deletes their homework. |
| HomeroomTeacher | Same as Teacher. |
| Student / Parent | A soft-deleted account can no longer log in. Deleted grades disappear from their views and averages, as they do today. |
| Supervisor / Principal | Restore permissions follow their existing `change_<model>` permissions in `/admin/`. They cannot purge unless they are in the Admin group. |

## Acceptance criteria

- **AC-1:** Given a live row of any model in scope, when `obj.delete()` is
  called, then the row still exists with `is_deleted=True`, `deleted_at` set
  and `deletion_batch` set. `Model.objects` no longer returns it, and
  `Model.all_objects` still does.
- **AC-2:** Given a `SubjectOffering` with lessons, topics, topic grades,
  assignments, subject grades, quarter grades, homeworks, homework grades and
  schedules, when it is deleted, then all of them are soft-deleted and share
  one `deletion_batch`. When the offering is restored, exactly that set comes
  back.
- **AC-3:** Given a child row that was soft-deleted before its parent was, when
  the parent is deleted and then restored, then the child stays deleted.
- **AC-4:** Given a soft-deleted child whose `CASCADE` parent is also deleted,
  when the child alone is restored, then `ValidationError` is raised, it names
  the parent, and nothing changes.
- **AC-5:** Given row `A` with a value covered by a unique rule, when `A` is
  soft-deleted, then a new row `C` with the same value can be created. When
  `A` is then restored, `ValidationError` is raised, it names `C`, and `A`
  stays deleted. There is one test for each converted constraint, including
  `CustomUser.username` and `AcademicYear(school, year)`.
- **AC-6:** Given a soft-deleted user, when they try to log in through the
  session login or through JWT (by obtaining a token, or by using an existing
  access token), then authentication fails. The user is also absent from
  `CustomUser.objects` and `CustomUser.in_school`.
- **AC-7:** Given a `TeachingAssignment` with homeworks:
  - When it is deleted, its homeworks stay live.
  - When it is hard-deleted (purged), each homework's `teaching_assignment`
    becomes `NULL`.
  - The homework API serializes a homework with a `NULL` teaching assignment
    without error.
- **AC-8:** Given a `Homework` with an attachment:
  - When it is soft-deleted, the stored file still exists.
  - Its mirror `SubjectAssignment` and the mirror grades are soft-deleted in
    the same batch.
  - When it is purged, the file is removed from storage.
- **AC-9:** `QuerySet.delete()` and the admin "delete selected" action
  soft-delete, and they record the acting user in `deleted_by` when one is
  known.
- **AC-10:** Given a live assignment or topic with one soft-deleted grade, then
  quarter averages and every other aggregate fixed in the read-path audit
  leave that grade out. There is one test for each aggregation site.
- **AC-11:** On `/admin/trash/`:
  - Only deleted rows of the active school are listed, grouped by batch.
  - Restoring a batch brings it back.
  - Purging a batch hard-deletes it.
  - A purge request from a user who is neither a superuser nor in the Admin
    group gets 403.
- **AC-12:** `manage.py check` reports `softdelete.E001` for a model that a
  soft-deletable model reaches by a `CASCADE` edge, when that model is not
  itself soft-deletable and is not on the exemption list.
- **AC-13:** Given a row with a live `PROTECT` dependent (for example, a
  student with a `QuarterGradeSnapshot`), when it is soft-deleted, then
  `ProtectedError` is raised and nothing is deleted. This is the same rule a
  hard delete follows today.
- **AC-14:** `DELETE` on a homework `SubjectAssignment` is still refused, as
  spec 0007 requires.
- **AC-15:** Given any `School`, including one with no dependents, then the
  `School` admin offers no delete: its delete view is refused for every user,
  superusers included, and the changelist has no "delete selected" action.
  `School` has no `is_deleted` field, and no API endpoint deletes a school.

## API contract

No new endpoints. Existing `DELETE` endpoints keep their status codes, and
their effect becomes a soft delete.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/admin/trash/` | Staff with `view_<model>` | Deleted-row counts per model, for the active school |
| GET | `/admin/trash/<app>/<model>/` | Staff with `view_<model>` | Deleted rows grouped by `deletion_batch` |
| POST | `/admin/trash/batch/<uuid>/restore/` | Staff with `change_<model>` | 400-style admin error message if a restore guard fails (AC-4, AC-5) |
| POST | `/admin/trash/batch/<uuid>/purge/` | Superuser or Admin group, plus `delete_<model>` | Shows a confirmation page first |

## Data model

- `SoftDeleteMixin` (`core/models.py`) gains a field:
  `deletion_batch = UUIDField(null=True, db_index=True)`.
- Every model in scope gets `is_deleted`, `deleted_at`, `deleted_by` and
  `deletion_batch`.
- Every unique rule on a model in scope becomes a partial
  `UniqueConstraint(..., condition=Q(is_deleted=False))`. A constraint that
  already has a condition gets `is_deleted=False` ANDed into it.
- Exceptions to the partial-constraint rule:
  - Every `*_id_school_unique` constraint stays unconditional, because the
    composite FKs from `home/0040` reference it.
  - Profile `OneToOneField(user)` stays unique. A user and their profile are
    always restored together.
  - `ClassGroupCollection.major` (`OneToOneField`) stays unique. A collection
    is never created or deleted on its own: it is created by binding subgroups
    and is soft-deleted and restored only together with its major
    `ClassGroup` (owner, 2026-10-15).
- `CustomUser.username`: the field-level unique flag is replaced by a partial
  constraint. `auth.E003` is silenced in settings, with a comment explaining
  why.
- `Homework.teaching_assignment` becomes `on_delete=SET_NULL, null=True,
  blank=True`.
- Migrations are additive (new columns default to `is_deleted=False`) plus
  constraint swaps. No backfill is needed.

## Permissions

1. **Route-level:** No change for the API. The trash views require staff
   access and check model permissions, as described in the API contract.
2. **Object-level:** No change. Deleted rows are invisible, so they are never
   reached by the object checks.
3. **View-level:** Querysets exclude deleted rows through the default
   managers. The read-path audit adds explicit filters where a manager cannot
   apply (aggregates and joins across reverse relations).

## Non-functional

- **Performance:** Soft delete issues one `UPDATE` per model in the cascade
  tree, not one per row. Every default query gains an `is_deleted = false`
  predicate, which is indexed.
- **Security:**
  - Deleted users cannot authenticate.
  - The trash page is scoped to the active school, so it cannot list another
    tenant's rows.
  - Purge is limited to the Admin group and superusers.
- **Migrations:** Reversible. The constraint swaps run inside one transaction
  per app.

## Resolved questions

- **Does soft delete honor `PROTECT` from `QuarterGradeSnapshot.student`,
  `.offering` and `.frozen_by`?** Yes, AC-13 stands (owner, 2026-10-15). A
  student or offering with a frozen quarter cannot be deleted, and neither can
  the user who froze it. Only admins and supervisors can freeze, so
  `frozen_by` is always one of them.
- **How does `ClassGroupCollection.major` (a `OneToOneField`) square with
  G-4?** It is on the exception list under Data model: a collection only lives
  and dies with its major class group (owner, 2026-10-15).
- **Should a soft-deleted `School` block logins for its users?** Moot.
  `School` is out of scope and cannot be deleted through the application
  (owner, 2026-10-15; AC-15).
