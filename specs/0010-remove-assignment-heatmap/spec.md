---
id: 0010
slug: remove-assignment-heatmap
title: Remove the assignment heatmap endpoints
status: in-progress
owner: bekzhan
created: 2026-10-01
updated: 2026-10-01
supersedes: 0005
---

# 0010 — Remove the assignment heatmap endpoints

> Supersedes **only AC-24 and AC-25** of spec 0005, which describe how the
> two assignment heatmaps handle drafts. It also drops the "(except the
> heatmap, AC-24)" carve-out from 0005 AC-23. Every other part of 0005 stands.

## Problem

The frontend no longer calls either assignment heatmap. It has removed the
wrapper and response types for them, and it no longer reads `can_heatmap`
from `analytics/assignment-offerings/`. The backend still carries both
endpoints, a matrix builder only they use, and a flag nothing reads.

## Goals

- G-1 Remove `GET /api/v1/analytics/offerings/<id>/assignment-heatmap/` and
  `GET /api/v1/analytics/teacher/offerings/<id>/assignment-heatmap/`, along
  with the code and serializers that only they use.
- G-2 Remove the unused `can_heatmap` field from `analytics/assignment-offerings/`.

## Non-goals

- `analytics/offerings/<id>/topic-heatmap/` and
  `analytics/offerings/<id>/attendance-heatmap/`. They serve different data
  and are still used.
- `analytics/assignment-offerings/` itself. It still backs the frontend's
  tables, filters and pickers. Only `can_heatmap` goes.
- The assignment trajectory and summary endpoints. Their payloads are
  unchanged.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Teacher, HomeroomTeacher | The two heatmap URLs return 404. `assignment-offerings/` rows no longer carry `can_heatmap`. |
| Others | None. They could not use the heatmaps anyway. |

## Acceptance criteria

- **AC-1** — Neither `/api/v1/analytics/offerings/<id>/assignment-heatmap/`
  nor `/api/v1/analytics/teacher/offerings/<id>/assignment-heatmap/` resolves.
- **AC-2** — `GET /api/v1/analytics/assignment-offerings/` rows have no
  `can_heatmap` key. `access`, `teaching_role` and `is_homeroom_class` are
  unchanged.
- **AC-3** — `topic-heatmap/` and `attendance-heatmap/` still resolve.
- **AC-4** — No subject analytics endpoint returns a draft assignment. With
  the heatmaps gone, 0005 AC-23 applies without exception.

## API contract

| Method | Path | Change |
|---|---|---|
| GET | `/api/v1/analytics/offerings/<id>/assignment-heatmap/` | Removed |
| GET | `/api/v1/analytics/teacher/offerings/<id>/assignment-heatmap/` | Removed |
| GET | `/api/v1/analytics/assignment-offerings/` | `can_heatmap` removed from each row |

## Data model

No change.

## Permissions

No change. `can_grade_offering` in `analytics_subject.py` existed only for the
heatmaps, so it is removed.

## Non-functional

- **Migrations**: none.
