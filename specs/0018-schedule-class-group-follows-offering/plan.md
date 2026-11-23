---
spec: 0018
status: done
updated: 2026-11-23
---

# 0018 — Implementation plan

## Approach

Make `offering.class_group` the single authority for an offering-bound
schedule, enforced at the lowest layer that every write passes through
(`SubjectSchedule.save()`), with the serializer mirroring the rule so its
`class_group is required` check sees the right value, and `SubjectOffering.save()`
pushing a changed class group down to its schedules. A data migration aligns
the existing rows.

Rejected: removing `SubjectSchedule.class_group` (free entries need it), and
keeping the 400 on a mismatch (the spec asks for the offering to win silently).

## Files to touch

| File | Change |
|---|---|
| `apps/lesson/migrations/0035_schedule_class_group_from_offering.py` | data-only backfill |
| `apps/lesson/models.py` | `SubjectSchedule.save()` copies `offering.class_group_id` |
| `apps/lesson/api/serializers.py` | `SubjectScheduleWriteSerializer.validate()` always takes the offering's class group; drop the mismatch 400 |
| `apps/home/models.py` | `SubjectOffering.save()` cascades a changed `class_group_id` to its schedules |
| `apps/lesson/tests/test_schedule_class_group_follows_offering.py` | AC tests |
| `apps/lesson/tests/test_schedule_minor_groups_api.py` | build the legacy NULL row with `update()`, since `save()` now fills it |

## Migrations

- Data-only, no schema change. `RunPython` over `_base_manager` (all rows,
  soft-deleted included, no school scope). Reverse is a no-op.

## Test plan

| AC | Test | File |
|---|---|---|
| AC-1 | `test_ac1_migration_aligns_class_group_with_offering` | `apps/lesson/tests/test_schedule_class_group_follows_offering.py` |
| AC-2 | `test_ac2_post_takes_offering_class_group_over_sent_one` | same |
| AC-3 | `test_ac3_post_without_class_group_takes_offering_class_group` | same |
| AC-4 | `test_ac4_patch_class_group_alone_keeps_offering_class_group` | same |
| AC-5 | `test_ac5_patch_to_other_offering_follows_new_offering` | same |
| AC-6 | `test_ac6_patch_offering_to_null_keeps_class_group_and_needs_description` | same |
| AC-7 | `test_ac7_offering_class_group_change_cascades_to_schedules` | same |
| AC-8 | `test_ac8_orm_save_takes_offering_class_group` | same |

## Rollout

- No config. Deploy runs the migration; it touches ~220 rows.
- Rollback: revert the code; the backfilled values are correct either way.

## Risks

| Risk | Mitigation |
|---|---|
| The 21 drifted timetables move class in the UI and analytics | Called out in the spec; intended |
| `queryset.update()` bypasses `save()` | Only the cascade and migration use it, and both write the offering's value |
