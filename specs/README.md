# Specs

Spec-driven development for Qadam Analytics. The spec is the source of truth
for *what* and *why*; the plan covers *how*; the tasks track *progress*. Code
follows the spec, not the other way round.

## Layout

```
specs/
  README.md              ← you are here
  templates/             ← copy these to start
    spec.md
    plan.md
    tasks.md
  backlog/               ← candidate work, not yet specs
    security-roadmap.md
  0001-platform-implementation/
    spec.md
  0002-teacher-interface/
    spec.md
  0003-cloudflare-origin-protection/
    spec.md
    plan.md              ← operational runbook
```

One directory per change, named `NNNN-short-slug`. Numbers are allocated in
order and never reused. A spec directory holds at most three files:

| File | Answers | Written when |
|---|---|---|
| `spec.md` | What changes and why, with acceptance criteria | First — before any code |
| `plan.md` | How it is built, which files, which tests | After the spec is `approved` |
| `tasks.md` | What is left to do | Alongside the plan |

Small changes need only a `spec.md`. Do not manufacture a plan for a one-line fix.

## Workflow

```
   /spec-new  →  review  →  /spec-plan  →  /spec-tasks  →  /spec-implement
     draft       approved     draft         in-progress       shipped
```

1. **`/spec-new <idea>`** — interviews you, then writes `specs/NNNN-slug/spec.md`
   at `status: draft`. No code is written.
2. **You review it.** This is the human gate, and the only one that matters.
   Flip `status:` to `approved` when the behaviour described is the behaviour
   you want. Everything downstream inherits whatever you approve here.
3. **`/spec-plan NNNN`** — reads the approved spec, writes `plan.md`.
4. **`/spec-tasks NNNN`** — derives `tasks.md` from the plan, one task per AC.
5. **`/spec-implement NNNN`** — works the task list, ticking boxes as it goes,
   and stops at the first thing the spec does not cover rather than guessing.
6. **`/spec-status`** — shows every spec and where it stands.

## Rules

- **The spec precedes the code.** If implementation reveals the spec is wrong,
  stop and amend the spec, then continue. A spec that drifts from the code is
  worse than no spec.
- **Acceptance criteria are testable.** Each AC gets a test named after it. An
  AC no test can fail on is not an AC, it is a wish.
- **Non-goals are binding.** They are the record of what was deliberately left
  out, so the next person does not "fix" it by accident.
- **Status is current.** A spec at `in-progress` that shipped last month is
  misinformation.
- **Superseding beats editing.** For a change of direction, write a new spec
  with `supersedes: NNNN` and set the old one to `superseded`. Keep the history.

## Status values

| Status | Meaning |
|---|---|
| `draft` | Being written or reviewed. Do not implement. |
| `approved` | Human-reviewed. Ready to plan and build. |
| `in-progress` | Being implemented. |
| `shipped` | Merged and deployed. |
| `superseded` | Replaced by a later spec. Kept for history. |

## Validation

`python scripts/check_specs.py` validates frontmatter, ids, slugs and status
values across every spec. It takes no dependencies beyond the standard library,
so it is safe to run in CI.

## Related documents

- `specs/backlog/security-roadmap.md` — prioritised security backlog. When an
  item is picked up it graduates into a numbered spec, and the backlog entry
  links to that spec.
- `CLAUDE.md` — architecture and conventions for agents
- `.claude/commands/spec-*.md` — the slash commands that drive this workflow

Infrastructure specs (like 0003) may put an operational runbook in `plan.md`.
Their ACs are checked by a verification command rather than pytest. Say so in
the spec. Documents that belong next to their code stay there, e.g.
`scripts/google_sheets/TEACHER_INSTRUCTIONS_RU.md`.

Only numbered spec directories, `templates/` and `backlog/` belong under
`specs/`. The checker rejects any other directory.
