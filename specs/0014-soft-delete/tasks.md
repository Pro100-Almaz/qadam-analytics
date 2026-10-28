---
spec: 0014
updated: 2026-10-15
---

# 0014 — Tasks

Ordered and small enough to land individually. Each task names the AC it
serves, so nothing gets implemented that the spec did not ask for. Tests come
before the code they cover; each task should leave the suite green.

## 1. Core mechanism

- [x] **T-1** (AC-1, AC-9, AC-13) — Tests in `core/tests/test_soft_delete.py`:
  `test_ac1_delete_sets_is_deleted_and_hides_row` (parametrized over the
  registry), `test_ac9_queryset_and_admin_bulk_delete_are_soft` (queryset half;
  the admin half lands with T-24), `test_ac13_protect_dependent_blocks_soft_delete`.
- [x] **T-2** (AC-1, AC-9, AC-13) — `core/models.py`: `SoftDeleteMixin` gains
  `deletion_batch`; `delete(user=None)` → `soft_delete`; `hard_delete()`;
  `restore()` by batch. `SoftDeleteQuerySet` (`delete`, `hard_delete`,
  `restore`, `alive`, `dead`) and managers built with `from_queryset`.
- [x] **T-3** (AC-1, AC-3, AC-4, AC-5, AC-13) — New `core/soft_delete.py`: tree
  walker (`CASCADE` recurse, `PROTECT`/`RESTRICT` raise, `SET_NULL`/`DO_NOTHING`
  untouched, already-deleted rows keep their batch, `soft_delete_extra()` hook),
  one `UPDATE` per model inside `atomic`, restore guards (deleted `CASCADE`
  parent → `ValidationError`; `IntegrityError` → `ValidationError` naming the
  conflicting live row), `soft_delete_models()` registry.
- [x] **T-4** (AC-1) — Let `core/checks.py` (`check_scoped_models_have_a_scoped_manager`,
  `UNSCOPED_DEFAULT_MANAGER`) and `core/admin_mixins.py`
  (`has_unscoped_default_manager`) accept the new manager classes.
- [x] **T-5** (AC-1) — Migrations adding `deletion_batch` to the models that
  already use the mixin (`lesson.Lesson`, achievement models).

## 2. authentication

- [x] **T-6** (AC-5, AC-6, AC-15) — Tests: `apps/authentication/tests/test_soft_delete_user.py::test_ac6_deleted_user_cannot_authenticate`
  (session login, JWT obtain, existing access token, absent from `objects` and
  `in_school`) and `::test_ac15_school_cannot_be_deleted_in_app`;
  `core/tests/test_soft_delete_unique.py::test_ac5_unique_value_reusable_after_delete`
  case for `CustomUser.username`.
- [x] **T-7** (AC-1, AC-5, AC-6) — Mixin on `CustomUser`, `Student`,
  `Teacher`, `Parent`, `Supervisor`, `ClubManager`, `PsychologicalState`.
  `SoftDeleteUserManager` for `CustomUser.objects`; scoped and filtered
  `in_school`; `all_objects`. `username` field-unique →
  `user_unique_live_username`. Silence `auth.E003` in `core/settings.py` with a
  comment pointing at this spec.
- [x] **T-7a** (AC-15) — `SchoolAdmin.has_delete_permission` returns `False`
  for everyone; drop the now-unused `_has_dependents`.
- [x] **T-8** (AC-1, AC-5) — `makemigrations authentication`.

## 3. home

- [x] **T-9** (AC-5, AC-14) — Tests: AC-5 cases for `AcademicYear(school, year)`,
  `one_active_per_school`, `TeachingAssignment`, `HomeroomTeacherAssignment`,
  `Enrollment`, `QuarterGrader`, `SubjectAssignment`, `SubjectGrade`,
  `QuarterGrade`; `apps/home/tests/test_soft_delete_cascade.py::test_ac14_homework_assignment_direct_delete_still_refused`.
- [x] **T-10** (AC-1, AC-5, AC-14) — Mixin on the home models in scope; drop
  explicit `objects = SchoolScopedManager()` lines; rebase
  `MinorClassGroupManager`; partial constraints per the plan table (leave
  `*_id_school_unique` unconditional); remove the `TeachingAssignment.delete`
  override; `SubjectAssignment.delete` keeps the 0007 refusal then soft-deletes.
  Audit `Enrollment.enroll_student` and `ClassGroupCollection` creation for
  upserts against deleted rows.
- [x] **T-11** (AC-1, AC-5) — `makemigrations home`.

## 4. lesson

- [x] **T-12** (AC-5, AC-7, AC-8) — Tests: AC-5 cases for `Topic`, `TopicGrade`,
  `SubjectSchedule`, `ScheduleSession`, `ScheduleAttendance`, `HomeworkGrade`;
  `apps/lesson/tests/test_homework_soft_delete.py::test_ac7_teaching_assignment_delete_keeps_homework`
  and `::test_ac8_homework_files_kept_until_purge`.
- [x] **T-13** (AC-1, AC-5) — Mixin on `Topic`, `TopicGrade`,
  `MergedLessonComment`, `SubjectSchedule`, `ScheduleSession`,
  `ScheduleAttendance`, `Homework`, `HomeworkGrade`; partial constraints.
- [x] **T-14** (AC-7) — `Homework.teaching_assignment` → `SET_NULL, null=True,
  blank=True`; guard `NULL` in `apps/lesson/api/serializers.py` and
  `apps/lesson/admin.py`.
- [x] **T-15** (AC-8) — File removal moves from `Homework.delete` to
  `hard_delete`; `soft_delete_extra()` on `Homework` (mirror
  `SubjectAssignment` by `detail_id`), `HomeworkGrade` and `SubjectGrade`
  (each other's mirror). Mirror deletes in `homework_sync` become soft; audit
  its `get_or_create`/`update_or_create`; `sync_homework_assignments` ignores
  deleted rows.
- [x] **T-16** (AC-1, AC-5, AC-7) — `makemigrations lesson`.

## 5. student_report, notification, achievement

- [x] **T-17** (AC-1, AC-5) — Mixin on `StudentReport` and `Notification`;
  `Club.soft_delete` calls `super()`; `unique_active_club_attendance` gets
  `is_deleted=False` if missing (with an AC-5 case if changed);
  `makemigrations student_report notification achievement`.

## 6. Cascade, check, and existing tests

- [x] **T-18** (AC-2, AC-3, AC-4) — `apps/home/tests/test_soft_delete_cascade.py`:
  `test_ac2_offering_delete_cascades_one_batch_and_restores`,
  `test_ac3_previously_deleted_child_stays_deleted_on_restore`,
  `test_ac4_restore_child_of_deleted_parent_refused`; fix whatever they expose.
- [x] **T-19** (AC-12) — `core/tests/test_soft_delete_checks.py::test_ac12_check_flags_hard_cascade_child`.
- [x] **T-20** (AC-12) — `softdelete.E001` in `core/checks.py`, with the
  exemption list (`QuarterGradeSnapshot`, `Attachment`, lookup tables, M2M
  through rows). `manage.py check` and the enforce-mode check stay clean.
- [x] **T-21** (AC-1, AC-7, AC-8) — Update existing tests that assert real
  removal (`_base_manager` counts after delete, `TeachingAssignment.delete`
  removing homework, homework delete removing files).

## 7. API delete sites and read-path audit

- [x] **T-22** (AC-9) — Pass `user=request.user` to `delete()` at the API delete
  sites listed in the plan; extend the AC-9 test to cover one of them.
- [x] **T-23** (AC-10) — Read-path audit of the files listed in the plan. For each
  site that aggregates or joins a soft-deletable child, write
  `test_ac10_<site>_excludes_deleted_grade` and then add the
  `is_deleted=False` / `filter=Q(...)` fix. List the audited sites in this
  task when done.

  Audited sites, each with a `test_ac10_*` test (`apps/{lesson,home,achievement}/tests/test_soft_delete_read_paths.py`):
  - `apps/home/repo/students.py` `calculate_quarter_grade`: the quarter average.
    It reads through default managers, so it was already clean; the test pins it.
  - `apps/lesson/services.py` `build_graded_percent_map`: `topicgrade__is_deleted`.
  - `apps/lesson/api/serializers.py`: `LessonListSerializer.get_graded_percent`
    (`topicgrade__`), plus `LessonDetailSerializer.get_students` /
    `get_student_grades` and `GradingDataSerializer._get_students` (`enrollments__`).
  - `apps/lesson/api/attendance_views.py` `apply_schedule_filters`
    (`offering__teaching_assignments__`).
  - `apps/lesson/api/homework.py` `grade_queryset`, homeroom branch (`student__enrollments__`).
  - `apps/lesson/admin.py` `HomeworkAdmin` grade count.
  - `apps/home/api/views/assignments.py` `grade_queryset` (homeroom branch) and
    `homeroom_grade_queryset`; `quarter_grades.py` `homeroom_quarter_grade_queryset`.
  - `apps/home/api/views/students.py` `StudentClassmatesAPIView`.
  - `apps/home/api/views/teacher_dashboard.py` `include_empty=false` (`assignments__`).
  - `apps/home/api/views/teachers.py` `TeacherDetailAPIView` parent link.
  - `apps/home/admin.py` `AssignmentCategoryAdmin` assignment count and
    `BaseClassGroupAdmin` student and offering counts.
  - `apps/achievement/api/services.py` `club_base_queryset` member and attendance-date
    counts; `club_views.py` `ClubAvailableStudentListAPIView` (`enrollments__`).
  - `apps/authentication/models.py` `assign_intake_year_for_student`: read
    `AcademicYear._base_manager`, so a deleted year could be stamped.

  Checked and left alone: `ClassGroup.objects.filter(collections__major=…)` (a
  collection is deleted only with its major, and the major is the live
  argument), `Enrollment…class_group__subject_offerings__id__in` in
  `build_graded_percent_map` (the offering ids come from live lessons), and
  `ClubSession.all_objects` in the club attendance history (that history
  deliberately includes deleted sessions). Every AC-10 test above except the
  quarter-average one was mutation-checked: it fails with its filter removed.

## 8. Admin

- [x] **T-24** (AC-9) — `SoftDeleteAdminMixin` in `core/admin_mixins.py`
  (live changelist, soft delete and "delete selected" recording the user,
  confirmation page showing the walker tree); add it to every ModelAdmin of a
  model in scope; admin half of the AC-9 test.
- [x] **T-25** (AC-11) — `core/tests/test_admin_trash.py::test_ac11_trash_lists_restores_purges_scoped`.
- [x] **T-26** (AC-11) — `core/admin_trash.py` views (index, per-model batches,
  restore, purge with confirmation, purge limited to superuser/Admin group),
  URLs in `core/admin.py`, templates under `apps/templates/admin/trash/`,
  "Trash" link in `admin/base_site.html`. Rows soft-deleted before 0014 have
  no `deletion_batch` and are not backfilled, so the trash addresses each one
  as a batch of one under a computed id (`legacy_batch_id`), with no write.

## 9. Close out

- [x] **T-27** (supersedes 0005) — Add a note to spec 0005 pointing at this spec
  for the two superseded behaviours (plan step 6).

## Done when

- [x] Every AC has a passing test
- [x] `pytest` green
- [x] `ruff check .` clean
- [x] `makemigrations --check --dry-run` reports no drift
- [x] Spec `status:` set to `shipped`
