---
id: 0016
slug: active-role-request-context
title: Request-scoped authorization for multi-role users
status: shipped
owner: bekzhan
created: 2026-11-07
updated: 2026-11-07
supersedes:
---

# 0016 — Request-scoped authorization for multi-role users

## Problem

The frontend selects one UI role at a time, but the API currently evaluates
all Django groups assigned to the user. A permission or queryset branch from
an inactive role can therefore affect the current request.

## Goals

- G-1 Validate `X-Active-Role` centrally against the authenticated user's
  assigned roles and expose the result as `request.active_role`.
- G-2 Scope API permissions and querysets to that active role.
- G-3 Treat a genuine `HomeroomTeacher` assignment as the frontend's
  `teacher` context without losing homeroom capabilities.
- G-4 Keep public authentication/bootstrap requests and existing single-role
  clients compatible when the header is absent.

## Non-goals

- Persisting the active role in the database, session, or JWT.
- Adding `homeroom_teacher` as a frontend-selectable role.
- Changing role assignments or the existing role hierarchy.

## Acceptance criteria

- **AC-1** — An assigned supported role is accepted and exposed on the request.
- **AC-2** — Different valid headers on consecutive requests select different
  authorization and queryset branches without leaking state.
- **AC-3** — Unsupported and unassigned roles return structured 403 responses.
- **AC-4** — `teacher` is valid for `Teacher` or `HomeroomTeacher`; homeroom
  permissions still require the latter group.
- **AC-5** — Headerless public authentication, token refresh, and initial
  `/auth/me/` requests work; a single canonical role is inferred elsewhere.
- **AC-6** — A multi-role authenticated request without the header is 403.
- **AC-7** — Permissions and querysets from inactive roles are not applied.
- **AC-8** — CORS permits `X-Active-Role`.

## API contract

Supported lowercase values are `admin`, `teacher`, `student`, `supervisor`,
`principal`, `parent`, `clubmanager`, and `psychologist`.

Failures use HTTP 403 and a `{code, detail}` body with one of
`invalid_active_role`, `active_role_not_assigned`, or `active_role_required`.

## Data model

No change.
