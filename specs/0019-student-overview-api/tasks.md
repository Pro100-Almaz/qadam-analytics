---
spec: 0019
updated: 2026-11-24
---

# 0019 — Tasks

Ordered and small enough to land individually. Each task names the AC it
serves, so nothing gets implemented that the spec did not ask for. There is
no migration task, because the plan has no model changes.

## Shared pieces

- [x] **T-1** (AC-26, AC-29–AC-32) — `core/pagination.py`:
  `StudentListPagination` (page size 20, max 100, `page_size` param).
- [x] **T-2** (AC-28) — test `test_ac28_detail_still_embeds_current_and_history`.
  It should pass before any change, as a guard.
- [x] **T-3** (AC-24, AC-28) — extract `psychological_state_record(state)`
  from `StudentDetailSerializer.get_psychological_states`. T-2 stays green.

## Paginated lists

- [x] **T-4** (AC-29, AC-30, AC-32) — tests in
  `apps/achievement/tests/test_student_lists_pagination.py`.
- [x] **T-5** (AC-29, AC-30, AC-32) — paginate GET on
  `AchievementListCreateAPIView` and `ReadingEntryListCreateAPIView`, with a
  stable `-id` tie-break. POST is untouched.
- [x] **T-6** (AC-31, AC-32) — test in
  `apps/student_report/tests/test_report_list_pagination.py`.
- [x] **T-7** (AC-31, AC-32) — `StudentReportListView.pagination_class`.

## Psychological-states list

- [x] **T-8** (AC-24–AC-27) — tests in
  `apps/home/tests/test_student_psychological_states_api.py`.
- [x] **T-9** (AC-24–AC-27) — `StudentPsychologicalStateListAPIView`, plus
  the `students/<pk>/psychological-states/` route.

## Overview permission

- [x] **T-10** (AC-20–AC-23) — permission tests in
  `apps/home/tests/test_student_overview_api.py`.
- [x] **T-11** (AC-20–AC-22c) — `can_view_student_overview` in
  `core/permissions.py`.

## Attention flags (pure)

- [x] **T-12** (AC-12–AC-19) — tests in
  `apps/home/tests/test_student_attention_flags.py`.
- [x] **T-13** (AC-12–AC-19) — `STUDENT_ATTENTION_THRESHOLDS` in
  `core/settings.py`, plus `attention_flags` and `absence_streak` in
  `apps/home/services.py`.

## Overview endpoint

- [x] **T-14** (AC-1–AC-11, perf) — data tests in
  `apps/home/tests/test_student_overview_api.py`, plus
  `test_overview_query_count_is_bounded`.
- [x] **T-15** (AC-5, AC-7–AC-11, AC-14) — repo queries in
  `apps/home/repo/student_overview.py`.
- [x] **T-16** (AC-1–AC-11) — `resolve_quarter` and `build_student_overview`
  in `apps/home/services.py`.
- [x] **T-17** (AC-1, AC-3, AC-23) — `StudentOverviewQuerySerializer`,
  `StudentOverviewAPIView`, and the `students/<pk>/overview/` route. T-10 and
  T-14 go green.

## Done when

- [x] Every AC has a passing test
- [x] `pytest` green (1200 passed)
- [x] `ruff check .` clean (CI's linter)
- [x] `manage.py check` and `SCHOOL_SCOPE_MODE=enforce manage.py check` pass
- [x] `makemigrations --check --dry-run` reports no drift
- [ ] Spec `status:` set to `shipped` (left at in-progress until merged and deployed, per specs/README.md)
