---
spec: NNNN
updated: YYYY-MM-DD
---

# NNNN — Tasks

Ordered and small enough to land individually. Each task names the AC it
serves, so nothing gets implemented that the spec did not ask for.

- [ ] **T-1** (AC-1) — …
- [ ] **T-2** (AC-1) — …
- [ ] **T-3** (AC-2) — …

## Done when

- [ ] Every AC has a passing test
- [ ] `pytest` green
- [ ] `ruff check .` clean
- [ ] `makemigrations --check --dry-run` reports no drift
- [ ] Spec `status:` set to `shipped`
