---
spec: 0018
updated: 2026-11-23
---

# 0018 — Tasks

- [x] **T-1** (AC-1) — Data migration `lesson/0035` aligning `class_group` with the offering.
- [x] **T-2** (AC-8) — `SubjectSchedule.save()` copies `offering.class_group_id`.
- [x] **T-3** (AC-2..AC-6) — `SubjectScheduleWriteSerializer.validate()`: offering's class group always wins; drop the mismatch 400.
- [x] **T-4** (AC-7) — `SubjectOffering.save()` cascades a changed class group to its schedules.
- [x] **T-5** (AC-1..AC-8) — Tests named after each AC; fix the legacy-row test.

## Done when

- [x] Every AC has a passing test
- [x] `pytest` green
- [x] `makemigrations --check --dry-run` reports no drift
- [x] Spec `status:` set to `shipped`
