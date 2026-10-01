---
spec: 0005
updated: 2026-09-30
---

# 0005 — Tasks

- [x] **T-1** (AC-1–4, 6–11) — `AssignmentCategory`, `SubjectAssignment` fields and checks, migration `home/0041`
- [x] **T-2** (AC-12) — backfill migration `lesson/0029`
- [x] **T-3** (AC-13–15, 17–21) — `homework_sync` and model hooks, bulk create, `TeachingAssignment.delete`
- [x] **T-4** (AC-16, 11, 5) — subject-assignment serializers and views, categories endpoint
- [x] **T-5** (AC-5, 23, 24, 25) — analytics, grade sheet, draft filtering
- [x] **T-6** (AC-2, 3) — admin
- [x] **T-7** (AC-22) — `sync_homework_assignments` command
- [x] **T-8** — tests for every AC

## Done when

- [x] Every AC has a passing test
- [x] `pytest` green
- [x] `pycodestyle apps/ core/` clean
- [x] `makemigrations --check --dry-run` reports no drift
- [x] Spec `status:` set to `shipped`
