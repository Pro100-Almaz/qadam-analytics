---
id: 0003
slug: cloudflare-origin-protection
title: Cloudflare origin protection for api.qadam.edu.kz
status: draft
owner: almaz
created: 2026-09-25
updated: 2026-09-25
---

# 0003 — Cloudflare origin protection

Graduated from [security backlog](../backlog/security-roadmap.md) item #1
(Critical · M). The step-by-step runbook is in [`plan.md`](plan.md).

## Problem

`api.qadam.edu.kz` resolves straight to the origin IP. nginx is the only thing
between the internet and the app: no edge WAF, no DDoS absorption, and
automated RCE/LFI/Docker-API probes show up in the nginx logs all the time.
Anyone can reach the origin by IP, so the nginx default-deny is the only
control in front of it.

## Goals

- G-1 Hide the origin IP behind Cloudflare's proxy.
- G-2 Accept `:80`/`:443` on the origin only from Cloudflare ranges.
- G-3 Add edge WAF, bot mitigation and rate limiting on top of the nginx limits.
- G-4 Keep nginx per-client rate limiting and access logs keyed on the real
  client IP.
- G-5 Keep TLS valid without depending on HTTP-01 reachability.

## Non-goals

- Proxying `dashboard.qadam.edu.kz`. It can stay DNS-only.
- A paid Cloudflare plan. The Free plan is enough to start.
- Replacing the nginx rate limits or default-deny. They stay as defense in depth.
- Setting HSTS at the edge. Django already sends it, and two sources could
  disagree.
- Caching API responses at the edge.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | no change |
| Teacher | no change |
| HomeroomTeacher | no change |
| Student | no change |
| Supervisor | no change |
| Principal | no change |
| Parent | no change |

This is infrastructure only. No user-visible behaviour should change.

## Acceptance criteria

These are infrastructure checks, so most are verified by a command rather than
pytest (`plan.md` → *End-to-end verification checklist*). AC-3 and AC-6 are
config-level and can also be asserted in the repo.

- **AC-1** — When `api.qadam.edu.kz` is resolved, it returns only Cloudflare
  IPs and never the origin IP.
- **AC-2** — Given a request through Cloudflare, `GET /healthz` returns 200
  with a `cf-ray` header.
- **AC-3** — Given a request proxied by Cloudflare, the nginx access log and
  rate-limit key record the client's real IP from `CF-Connecting-IP`, not a
  Cloudflare IP.
- **AC-4** — Given a connection to the origin IP from outside Cloudflare's
  ranges, `:443` and `:80` time out or are refused.
- **AC-5** — The origin serves a Cloudflare Origin CA certificate, and
  Cloudflare SSL mode is Full (strict).
- **AC-6** — `certbot` no longer runs, and nginx no longer references
  `/etc/letsencrypt`.
- **AC-7** — Given `GET /.env` sent to the public hostname, the response is
  403 from Cloudflare or 444 from the origin.
- **AC-8** — Given more than 10 requests in 1 minute from one IP to
  `/api/v1/auth/login/`, later requests are blocked at the edge.
- **AC-9** — Given an unauthenticated `GET /api/docs/`, the response is still
  403 (no regression).

## API contract

No change.

## Data model

No change.

## Permissions

No change to any of the three tiers.

## Non-functional

- **Security** — Nothing new is exposed. The origin private key lives on the
  host at mode 600 and is mounted read-only into nginx. It is never committed.
- **Availability** — Zero downtime if the phases run in order, with the
  firewall lockdown last. Each phase has a rollback in `plan.md`.
- **Maintenance** — Refresh the Cloudflare CIDR lists in nginx and the firewall
  every quarter. The origin cert expires after 15 years.

## Open questions

- [ ] Firewall mechanism: ufw, the cloud provider's security group, or
      iptables? (`plan.md` Phase 4, options A–C)
- [ ] Should one wildcard origin cert (`*.qadam.edu.kz`) cover the dashboard
      too, or should the cert be issued for `api.` only?
- [ ] Is `nginx/conf.d/certonly.conf` (bootstrap for HTTP-01) retired along
      with certbot?
