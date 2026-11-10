---
spec: 0017
updated: 2026-11-10
---

# 0017 — Tasks

- [x] **T-1** (AC-5, AC-17) — Model: `created_by`, `quarter`, drop `teaching_assignment`; migrations 0032–0034 with the backfill.
- [x] **T-2** (AC-13, AC-18) — `homework_sync`: `quarter` in the field map both ways, no reset on date change.
- [x] **T-3** (AC-14, AC-15) — `SubjectAssignment.save()` no longer derives; drop `derive_quarter`, `quarter_for_date_or_single_assignment`.
- [x] **T-4** (AC-1, AC-6–AC-8) — Homework create: required `quarter`, `created_by`.
- [x] **T-5** (AC-10–AC-12) — Homework update: optional `quarter`, both quarters authorised.
- [x] **T-6** (AC-9, AC-13, AC-14) — Subject-assignment create requires `quarter`; patch keeps the stored one.
- [x] **T-7** (AC-2–AC-5, AC-16) — Serializers, access on `Homework.quarter`, `?teacher=` and per-teacher list on `created_by`.
- [x] **T-8** — Admin and `HomeworkFactory`.
- [x] **T-9** — Tests for every AC; existing tests updated.

## Done when

- [x] Every AC has a passing test
- [x] `pytest` green
- [x] `ruff check .` clean
- [x] `makemigrations --check --dry-run` reports no drift
- [ ] Spec `status:` set to `shipped`
