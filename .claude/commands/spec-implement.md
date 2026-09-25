---
description: Implement a spec by working its task list
argument-hint: <spec id, e.g. 0003>
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Implement spec **$ARGUMENTS**.

## Steps

1. Read the spec, plan and tasks in `specs/$ARGUMENTS-*/`.
2. Set the spec's `status:` to `in-progress` if it is not already.
3. Work the tasks in order. After each one, tick its box in `tasks.md`.
4. **Stop and ask** the moment you hit something the spec does not cover.
   Amend the spec, get it re-approved, then continue — do not guess and do not
   silently widen scope beyond the stated non-goals.
5. Run everything through Docker Compose; this project is not set up to run
   locally:
   ```bash
   docker compose -f docker-compose.dev.yml exec appseed-app pytest --tb=short -q
   docker compose -f docker-compose.dev.yml exec appseed-app python manage.py makemigrations --check --dry-run
   ```
   Then `ruff check .`
6. When every box is ticked and the suite is green, set `status: shipped` and
   report honestly what passed, what failed, and anything you left out.

Report test failures with their output. Never describe unverified work as done.
