---
spec: 0019
status: done
updated: 2026-11-24
---

# 0019 — Implementation plan

> Written against spec 0019 as amended on 2026-11-24 (AC-22c: spec 0016 has
> no `homeroom_teacher` active role). The spec must be re-approved before
> implementation starts.

## Approach

**Overview.** A read-only `APIView` that resolves the student by user id,
checks the new `can_view_student_overview`, and calls one service function,
`build_student_overview(student, quarter)`.

The service reuses what already exists and fills the gaps with a few
aggregate queries:

- The student's own per-quarter averages come from `compute_child_grades`
  (`apps/home/services.py:123`), the same rule the parent endpoints use.
- Attendance counts come from `tally` / `counts`
  (`apps/lesson/api/analytics_attendance.py:108-140`).
- The class cohort comes from `enrolled_students`
  (`apps/lesson/api/analytics_common.py:244`).

The service turns the numbers into attention flags with a pure function,
`attention_flags(metrics, thresholds)`. Its thresholds come from
`settings.STUDENT_ATTENTION_THRESHOLDS`.

**Lists.** One shared `StudentListPagination` (page size 20, max 100,
`page_size_query_param='page_size'`) is used by the new
psychological-states list and the three existing lists. The
psychological-state record dict that `StudentDetailSerializer` builds inline
moves to a module-level function, so the embedded payload and the new list
cannot drift apart.

**Rejected alternatives:**

- *Assembling the overview from calls to the existing analytics views*
  (`StudentAttendanceSummaryAPIView` and others). Those return far more than
  the overview needs: weekday, month and rank blocks. Calling views from a
  view also hides the query cost.
- *Computing the class average as one `Avg` over all `QuarterGrade` rows of
  the class.* It weights students by how many subjects they have marks in,
  which is not the spec's "mean of student averages". It would also count
  rows from students who are no longer enrolled (AC-8).
- *A thresholds model editable in Django admin.* Not asked for. Spec G-2
  only needs a setting.

## Files to touch

| File | Change |
|---|---|
| `core/permissions.py` | add `can_view_student_overview(user, student)`. It admits: <br>• `is_admin_role` <br>• active role `psychologist` <br>• active role `parent` when `Parent.students` contains the student <br>• active role `teacher` when a `HomeroomTeacherAssignment` exists for the student's current major class group in the active year <br>It does not allow self-access. |
| `core/settings.py` | add the `STUDENT_ATTENTION_THRESHOLDS` dict with the spec defaults |
| `core/pagination.py` (new) | add `StudentListPagination(PageNumberPagination)`: 20 per page, max 100 |
| `apps/home/repo/student_overview.py` (new; `repo/students.py` turned out to hold legacy template views, not queries) | queries: <br>• `class_quarter_averages(class_group_id, academic_year_id) -> {q: avg}` <br>• `subject_quarter_grades(student, offerings, quarters) -> {(offering_id, q): grade}` <br>• `attendance_counts(student_ids, quarter)`, a pooled tally <br>• `absence_days(student, quarter) -> [(date, all_absent)]` <br>• `homework_counts(student, offerings, quarter, today)` <br>• `latest_psychological_state(student)` |
| `apps/home/services.py` | add: <br>• `resolve_quarter(academic_year, requested)`, the default-quarter rule <br>• `absence_streak(days)` <br>• `attention_flags(metrics, thresholds)`, pure, sorted per AC-18 <br>• `build_student_overview(student, quarter)` |
| `apps/home/api/serializers.py` | extract `psychological_state_record(state)` from `get_psychological_states`, behaviour unchanged (AC-28); add `StudentOverviewQuerySerializer` (`quarter` 1–4, optional) for the 400 in AC-3 |
| `apps/home/api/views/students.py` | add `StudentOverviewAPIView` (GET, lookup by user id, 404 for unknown) and `StudentPsychologicalStateListAPIView` (`ListAPIView`, Student pk, `can_view_student`, `?name=`, `-time_added, -id`) |
| `apps/home/api/urls.py` | add the routes `students/<int:pk>/overview/` and `students/<int:pk>/psychological-states/` |
| `apps/achievement/api/views.py` | paginate GET of `AchievementListCreateAPIView` and `ReadingEntryListCreateAPIView` with `StudentListPagination`; add a stable `-id` tie-break to the ordering; leave POST alone |
| `apps/student_report/api/views.py` | set `StudentReportListView.pagination_class = StudentListPagination` |

### Query details that decide correctness

- **Class quarter averages (AC-5, AC-7, AC-8)**:
  1. The cohort is `enrolled_students(class_group_id, active_year.id)`.
  2. One query over `QuarterGrade` filtered to `student__in=cohort` and
     to offerings in the active year, grouped with
     `.values('student_id', 'quarter').annotate(avg=Avg('grade'))`.
  3. Python takes the mean per quarter of those per-student averages.

  This is one query for all four quarters. The current-offering scope uses
  the class groups of each cohort student's active enrollments, through an
  `Exists` on `Enrollment(student=OuterRef('student'),
  class_group=OuterRef('offering__class_group'), status='active')`. A
  student's average therefore matches what `compute_child_grades` gives for
  that student.
- **Attendance**:
  - The student's numbers and the class's `class_rate` both use
    `tally(ScheduleAttendance.objects.filter(student__in=…,
    session__schedule__quarter=Q))`. That is one query each.
  - `rate` is re-rounded to 1 decimal, because `ratio` rounds to 2.
- **Streak (AC-14)**: `values('date').annotate(recorded=Count, absent=Count(filter))`
  for the student in `Q`, ordered by date. Python counts the run of days
  with `absent == recorded`, ending at the most recent recorded day.
- **Homework (AC-10)**: one `aggregate` over `Homework` filtered to
  `offering__in=current_offerings`, `is_active=True` and `quarter=Q`. It is
  annotated with `graded=Exists(HomeworkGrade(student, grade__isnull=False))`
  and counts `submitted`, `overdue` (`~graded & due_date < today`) and
  `pending`.
- **Default quarter (AC-2)**:
  1. Use `AcademicYear.current_quarter`.
  2. Failing that, use the highest `n` with `q{n}_end < today`.
  3. Failing that, use 1.

  If there is no active academic year, the overview returns 200 with every
  value null or zero (the same path as AC-4) and `quarter` from the param,
  or 1.

Expected query budget is about 12, independent of subject count. This is
asserted in the test suite.

## Migrations

None. No model changes.

## Test plan

| AC | Test | File |
|---|---|---|
| AC-1 | `test_ac1_overview_returns_contract_keys_for_quarter` | `apps/home/tests/test_student_overview_api.py` |
| AC-2 | `test_ac2_default_quarter_is_current_or_last_ended` | same |
| AC-3 | `test_ac3_invalid_quarter_is_400` | same |
| AC-4 | `test_ac4_empty_student_returns_nulls_and_zeros` | same |
| AC-5 | `test_ac5_average_and_class_average_for_quarter` | same |
| AC-6 | `test_ac6_previous_quarter_average_null_in_q1` | same |
| AC-7 | `test_ac7_by_quarter_always_four_entries` | same |
| AC-8 | `test_ac8_class_average_excludes_unenrolled_students` | same |
| AC-9 | `test_ac9_attendance_counts_rates_and_late_zero` | same |
| AC-10 | `test_ac10_homework_graded_counts_as_submitted` | same |
| AC-11 | `test_ac11_wellbeing_latest_ignores_soft_deleted` | same |
| AC-12 | `test_ac12_low_grade_flag_is_critical` | `apps/home/tests/test_student_attention_flags.py` |
| AC-13 | `test_ac13_falling_grade_flag_never_in_q1` | same |
| AC-14 | `test_ac14_absence_streak_warning_and_critical` | same |
| AC-15 | `test_ac15_low_attendance_thresholds_and_null_rate` | same |
| AC-16 | `test_ac16_overdue_homework_flag` | same |
| AC-17 | `test_ac17_wellbeing_drop_flag` | same |
| AC-18 | `test_ac18_attention_sorted_critical_first` | same |
| AC-19 | `test_ac19_threshold_setting_override_flips_flag` | same |
| AC-20 | `test_ac20_admin_roles_psychologist_and_homeroom_get_200` | `apps/home/tests/test_student_overview_api.py` |
| AC-20a | `test_ac20a_student_cannot_read_own_overview` | same |
| AC-21 | `test_ac21_parent_own_child_only` | same |
| AC-22 | `test_ac22_other_student_403_anonymous_401` | same |
| AC-22a | `test_ac22a_subject_teacher_gets_403` | same |
| AC-22b | `test_ac22b_other_class_or_past_year_homeroom_gets_403` | same |
| AC-22c | `test_ac22c_homeroom_with_non_teacher_active_role_gets_403` | same |
| AC-23 | `test_ac23_unknown_user_id_is_404` | same |
| (perf) | `test_overview_query_count_is_bounded` | same |
| AC-24 | `test_ac24_psych_states_paginated_newest_first` | `apps/home/tests/test_student_psychological_states_api.py` |
| AC-25 | `test_ac25_psych_states_name_filter` | same |
| AC-26 | `test_ac26_psych_states_page_size_capped_at_100` | same |
| AC-27 | `test_ac27_psych_states_permissions_match_detail` | same |
| AC-28 | `test_ac28_detail_still_embeds_current_and_history` | same |
| AC-29 | `test_ac29_achievements_paginated_with_filters` | `apps/achievement/tests/test_student_lists_pagination.py` |
| AC-30 | `test_ac30_reading_entries_paginated_with_filters` | same |
| AC-31 | `test_ac31_reports_honour_page_size` | `apps/student_report/tests/test_report_list_pagination.py` |
| AC-32 | `test_ac32_default_20_max_100_and_post_unchanged` | `apps/achievement/tests/test_student_lists_pagination.py` |

Tests AC-12 to AC-19 call `attention_flags` directly with metric dicts.
`test_ac19` uses pytest-django's `settings` fixture. One end-to-end overview
test also asserts that the flags appear in the response.

## Rollout

- No new env var. Thresholds are a settings dict, not decouple config, so
  `.env.production.example` is unchanged.
- No deploy ordering. The frontend already accepts both bare and paginated
  list responses.
- Rollback: revert the merge. Nothing persists.

## Risks

| Risk | Mitigation |
|---|---|
| Paginating the lists breaks an existing consumer | Checked: no existing test, template (`apps/templates`, `apps/static/js`) or script calls the achievements or reading-entries lists |
| The class-average cohort query is slow for large classes | One grouped query, with the cohort capped by class size (~30). Covered by the query-count test |
| `apps/home` importing from `apps/lesson/api` creates an import cycle | Import `tally` / `counts` / `enrolled_students` inside the repo functions |
| A student with no active major enrollment has no class | Class values and `class_rate` are null, and the student's own numbers still compute |
| Multi-role user: the homeroom check runs under the wrong active role | Checks go only through `user_has_active_role` (AC-22c) |
