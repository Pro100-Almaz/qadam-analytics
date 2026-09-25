---
spec: NNNN
status: draft          # draft | approved | in-progress | done
updated: YYYY-MM-DD
---

# NNNN — Implementation plan

> Written against an **approved** spec. If the spec changes, update it first —
> never let the plan silently redefine the behaviour.

## Approach

The shape of the change in a few sentences, and the alternative(s) rejected
with the reason.

## Files to touch

| File | Change |
|---|---|
| `apps/<app>/models.py` | |
| `apps/<app>/api/serializers.py` | |
| `apps/<app>/api/views/….py` | |
| `apps/home/repo/….py` | query lives here, not in the view |
| `apps/<app>/services.py` | business logic lives here, not in the view |
| `core/permissions.py` | |

## Migrations

```bash
docker compose -f docker-compose.dev.yml exec appseed-app python manage.py makemigrations
docker compose -f docker-compose.dev.yml exec appseed-app python manage.py migrate
```

- Additive or destructive?
- Backfill needed? Write it as a data migration, not a script.
- CI runs `makemigrations --check --dry-run` — no drift allowed.

## Test plan

One test per acceptance criterion, named after it.

| AC | Test | File |
|---|---|---|
| AC-1 | `test_…` | `apps/<app>/tests/test_….py` |

## Rollout

- Config / env vars added (remember `.env.production.example`)
- Deploy order, if it matters
- Rollback

## Risks

| Risk | Mitigation |
|---|---|
| | |
