---
description: Show every spec and its current status
allowed-tools: Bash, Read, Glob
---

Show the state of every spec.

Run `python scripts/check_specs.py` and read each `specs/*/spec.md` frontmatter,
then present a table: id, title, status, and — where `plan.md` or `tasks.md`
exist — the count of ticked versus total tasks.

Call out anything that looks stale:
- `in-progress` specs whose tasks are all ticked (should be `shipped`)
- `approved` specs with no plan
- specs with unanswered open questions
- validation errors from the checker
