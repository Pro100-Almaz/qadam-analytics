---
id: NNNN
slug: short-kebab-slug
title: Human readable title
status: draft          # draft | approved | in-progress | shipped | superseded
owner: 
created: YYYY-MM-DD
updated: YYYY-MM-DD
supersedes:            # spec id, if any
---

# NNNN — Title

## Problem

What is broken or missing today, and who feels it. Describe the current
behaviour concretely — no solutions here.

## Goals

- G-1 …
- G-2 …

## Non-goals

Explicitly out of scope. This is what stops scope creep during implementation.

- …

## Affected roles

This platform is role-driven; name every role whose experience changes.

| Role (Django Group) | Change |
|---|---|
| Admin | |
| Teacher | |
| HomeroomTeacher | |
| Student | |
| Supervisor | |
| Principal | |
| Parent | |

## Acceptance criteria

Numbered, testable, and written so a test can be named after each one.
Every AC must be falsifiable — avoid "works correctly".

- **AC-1** — Given <state>, when <action>, then <observable outcome>.
- **AC-2** — …

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/…` | Teacher, Admin | |

<details>
<summary>Request / response shapes</summary>

```json
{}
```

</details>

## Data model

Models added or changed, and the constraints that matter. Note any unique
constraints — `SubjectOffering` and `Enrollment` both carry them.

- `apps/<app>/models.py` — …
- Migration: additive / destructive / requires backfill

## Permissions

Address all three tiers (see `CLAUDE.md` → 3-tier permission model):

1. **Route-level** — `@role_required(...)` in `core/decorators.py`
2. **Object-level** — helpers in `core/permissions.py` (Admin/Supervisor/Principal bypass)
3. **View-level** — queryset filtering

## Non-functional

- **Performance** — query budget, N+1 risks, expected row counts
- **Security** — PII exposure, authz regressions
- **Migrations** — reversible? downtime?

## Open questions

- [ ] …
