# Security Roadmap — Qadam Analytics

> **Backlog, not a spec.** Items here are candidates. When one is picked up, it
> graduates into its own numbered spec (`/spec-new`), and its entry below links
> to that spec instead of carrying the detail.

Tracking doc for security hardening. Context: internet-exposed school platform
(`api.qadam.edu.kz`) handling minors' PII and grades, on a raw IP under constant
automated scanning. Last review: 2026-05-27.

Legend — **Severity**: Critical / High / Medium / Low · **Effort**: S (minutes) / M (hours) / L (days)

---

## Done (2026-05-27 hardening pass)

| Item | File |
|---|---|
| Stale-DNS upstream fix — `resolver 127.0.0.11` + per-request `$upstream_django` (also removed `max_fails` footgun) | `nginx/conf.d/django.conf` |
| Default-deny catch-all (`return 444` + `ssl_reject_handshake on`) for raw-IP / bad-Host | `nginx/conf.d/django.conf` |
| Deny hidden dotfiles (`.env`, `.git`) except `.well-known` | `nginx/conf.d/django.conf` |
| Gunicorn `--log-level` debug → info (stop logging PII/tokens) | `docker/entrypoint.sh` |
| Gunicorn `--forwarded-allow-ips` set (correct `X-Forwarded-Proto` trust) | `docker/entrypoint.sh` |
| Swagger/schema gated behind `IsAdminUser` | `core/settings.py` |
| `SECRET_KEY` fail-closed (removed committed default) | `core/settings.py` |
| `DB_PASSWORD` fail-closed in compose | `docker-compose.yml` |
| Pinned `certbot:latest` → `certbot:v2.11.0` | `docker-compose.yml` |

---

## Backlog (prioritized)

### 1. Put a CDN / WAF in front of the origin — **Critical · M**
**→ Spec [0003-cloudflare-origin-protection](../0003-cloudflare-origin-protection/spec.md)** (draft)

The single biggest risk reduction. Server is exposed on a bare IP with active
RCE/LFI/Docker-API probing and no edge filtering.

- Move DNS for `api.qadam.edu.kz` behind Cloudflare (proxied / orange-cloud).
- Restrict the origin firewall to accept `:443` only from Cloudflare IP ranges
  (so the raw IP can't be hit directly).
- Enable Cloudflare WAF managed rules + rate limiting + bot fight mode.
- Hides origin IP, adds DDoS protection, offloads TLS.

**Why:** neutralizes the bulk of the scanning seen in nginx logs; everything
else below is defense-in-depth behind this layer.

---

### 2. Redis authentication — **High · M**
Redis is the Celery broker + Django cache (holds session data / report payloads
with PII). Network-isolated today, but no auth = full data read + RCE via
`CONFIG SET` if any container is compromised or SSRF is found.

- `docker-compose.yml` redis service:
  `command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 128mb --maxmemory-policy allkeys-lru`
- Add `REDIS_PASSWORD=<strong-random>` to server `.env`.
- Update broker/cache URLs to include the password:
  - `CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0`
  - `CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/0`
  - `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/1`
- Coordinated restart: redis → app → celery-worker.

---

### 3. Bind dev DB/Redis to loopback — **High · S**
`docker-compose.dev.yml` publishes `5433:5432` and `6380:6379` on `0.0.0.0`.
If the dev box is internet-reachable, that's an unauthenticated Redis + exposed
Postgres directly on the public interface.

- Change to `"127.0.0.1:5433:5432"` and `"127.0.0.1:6380:6379"`.
- Confirm prod compose uses `expose:` (internal-only) — it does today; keep it that way.

---

### 4. Resource limits on all services — **Medium · S**
No `mem_limit`/`cpus` anywhere → a single probe loop or memory leak can OOM the
whole host (easy DoS on an actively-attacked box).

- Add per-service limits, e.g. app `mem_limit: 512m`, db `1g`, celery `512m`,
  redis already capped at 128mb.
- Compose v2: `deploy.resources.limits` or top-level `mem_limit`/`cpus`.

---

### 5. Multi-stage Dockerfile — **Low · M**
Build toolchain (`build-essential`, `gcc`, `libffi-dev`, `libpq-dev`) ships in
the runtime image → compilers available to an attacker post-compromise.

- Builder stage compiles wheels; final stage copies only wheels + runtime libs
  (`libpq5`). Shrinks image and attack surface.

---

### 6. CSP (Content-Security-Policy) header — **Medium · M**
No CSP today. For the server-rendered admin/template pages this leaves XSS
largely unmitigated.

- Add `django-csp` or an nginx `add_header Content-Security-Policy ...`.
- Start in report-only mode, tighten iteratively (the Argon theme uses inline
  styles/scripts — will need `nonce` or hashes).

---

### 7. Audit logging for sensitive actions — **Medium · L**
No structured audit trail for grade changes, bulk imports, role changes, or
the curriculum wipe-and-replace (when built). For a minors'-data platform this
is a compliance gap.

- Add an `AuditLog` model (actor, action, target, timestamp, before/after).
- Emit on: login, grade edit, enrollment change, role/group change, bulk import,
  curriculum import `--force`.

---

### 8. Dependency & image scanning in CI — **Medium · M**
- `pip-audit` (or `safety`) on `requirements.txt` in CI.
- Trivy/Grype scan on the built image.
- Dependabot or Renovate for automated dependency PRs.

---

### 9. Secrets hygiene — **Medium · M**
- Move from `.env` files to a secrets manager (Docker secrets, SOPS, or cloud
  KMS) for `SECRET_KEY`, `DB_PASSWORD`, `REDIS_PASSWORD`, `OPENAI_API_KEY`.
- Rotate `SECRET_KEY` and `DB_PASSWORD` if the old committed default
  (`S#perS3crEt_1122`) was ever used in any environment.
- Confirm `core/credentials/*.json` (Google service account) is never baked
  into the image — mount at runtime instead.

---

### 10. Tighten the nginx bot map — **Low · S**
The UA-based block (`python-requests|curl/`) is trivially spoofed and blocks
legitimate `curl` health checks. Keep as low-value noise reduction only; do not
treat as a control. Real controls = WAF (item 1) + rate limits + default-deny.

---

## Verification checklist (run after each deploy)

```bash
# secrets present (fail-closed will halt boot otherwise)
docker compose exec appseed-app env | grep -E 'SECRET_KEY|DB_PASSWORD'

# nginx config valid BEFORE reload
docker compose exec nginx nginx -t

# default-deny works: valid host serves, raw IP rejected
curl -sI https://api.qadam.edu.kz/healthz        # expect 200
curl -skI https://<raw-ip>/                       # expect connection reset / 444

# swagger locked down
curl -sI https://api.qadam.edu.kz/api/docs/      # expect 403 when unauthenticated

# DB/Redis not exposed on host (prod)
ss -tlnp | grep -E ':5432|:6379'                  # expect nothing on 0.0.0.0
```

---

## Notes

- DB password in Django (`core/settings.py`) was already fail-closed
  (`config('DB_PASSWORD')`, no default) — only the compose interpolation
  defaults needed fixing.
- TLS config is already strong (TLSv1.2/1.3, GCM ciphers, session tickets off,
  HSTS 2y + preload). No action needed.
- Cookie flags (`Secure`, `HttpOnly`, `SameSite=Lax`) and `server_tokens off`
  are already correct.
