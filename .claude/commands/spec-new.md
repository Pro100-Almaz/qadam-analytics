---
description: Start a new spec — interviews you, then writes specs/NNNN-slug/spec.md
argument-hint: <short description of the change>
allowed-tools: Bash, Read, Write, Glob, Grep
---

Create a new spec for: **$ARGUMENTS**

## Steps

1. Read `specs/README.md` and `specs/templates/spec.md`.
2. Allocate the next id: `ls specs | grep -E '^[0-9]{4}-' | sort | tail -1`.
   Increment it, zero-padded to four digits. Pick a short kebab-case slug.
3. **Explore before asking.** Search the codebase for the models, endpoints,
   permissions and existing tests the change touches, so your questions are
   informed rather than generic.
4. **Interview the user.** Ask only what you could not determine yourself, and
   only what changes the spec. Use the AskUserQuestion tool. Cover at minimum:
   - which roles are affected, and how their access differs
   - what is explicitly *out* of scope
   - the observable behaviour that marks success
   Do not ask about implementation — that belongs in the plan.
5. Write `specs/NNNN-slug/spec.md` from the template, at `status: draft`.
   - Every acceptance criterion must be falsifiable and testable.
   - Fill the affected-roles table for every role, using "no change" where true.
   - Address all three permission tiers.
   - Record anything you were unsure of under Open questions rather than
     inventing an answer.
6. Write **no code**. Print the path and ask the user to review and flip
   `status:` to `approved`.
