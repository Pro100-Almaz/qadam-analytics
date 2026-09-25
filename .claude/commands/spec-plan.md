---
description: Write the implementation plan for an approved spec
argument-hint: <spec id, e.g. 0003>
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Write the implementation plan for spec **$ARGUMENTS**.

## Steps

1. Read the spec at `specs/$ARGUMENTS-*/spec.md` and `specs/templates/plan.md`.
2. **Check the gate.** If `status:` is not `approved`, stop and say so — an
   unreviewed spec must not be planned against. Report which open questions
   remain unanswered.
3. Read the real code paths the change touches. Name actual files, not guesses.
   Respect the repo's layering (`CLAUDE.md`):
   - queries belong in `apps/home/repo/`, not views
   - business logic belongs in `services.py`, not views
   - permission helpers belong in `core/permissions.py`
4. Write `specs/$ARGUMENTS-*/plan.md`:
   - state the approach and the alternative you rejected, with the reason
   - map every acceptance criterion to a named test in a named file
   - say whether migrations are additive, destructive, or need a backfill
   - note any new env var, which also belongs in `.env.production.example`
5. Write **no code**. Summarise the approach and the main risk in a few lines.
