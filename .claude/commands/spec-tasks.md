---
description: Derive an ordered task list from a spec's plan
argument-hint: <spec id, e.g. 0003>
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Derive the task list for spec **$ARGUMENTS**.

## Steps

1. Read `specs/$ARGUMENTS-*/spec.md`, `specs/$ARGUMENTS-*/plan.md` and
   `specs/templates/tasks.md`. If the plan is missing, stop and say to run
   `/spec-plan $ARGUMENTS` first.
2. Write `specs/$ARGUMENTS-*/tasks.md`:
   - order tasks so each leaves the suite green
   - tag every task with the AC it serves — a task serving no AC is scope creep,
     so drop it or amend the spec
   - put the test task before the implementation task it covers
   - keep migration generation as its own task
3. Flag any acceptance criterion no task covers. Do not quietly invent tasks
   the plan does not support.
