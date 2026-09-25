# 0003 — Plan: Cloudflare origin protection

> Plan for [`spec.md`](spec.md). Written as an operational runbook, since most
> of the work is DNS, TLS and firewall changes rather than code. The repo
> changes are Phase 2 (`nginx/conf.d/django.conf`) and Phase 3
> (`docker-compose.yml`, `nginx/conf.d/django.conf`).

Implementation runbook for [security backlog](../backlog/security-roadmap.md) item #1 (Critical). Puts
Cloudflare in front of the origin to hide the IP, add WAF/DDoS/rate-limiting at
the edge, and stop the constant automated scanning currently hitting the raw
IP `89.35.125.68`.

**Effort:** ~half a day, mostly waiting on DNS propagation.
**Downtime:** zero if you follow the phase order (firewall lockdown last).

---

## Two critical gotchas — read first

### 1. nginx rate limiting will break

`nginx/conf.d/django.conf` zones key on `$binary_remote_addr`. Once Cloudflare
proxies traffic, every request arrives from a Cloudflare IP, so all users
collapse into one rate-limit bucket. **Phase 2 fixes this** by restoring the
real client IP from `CF-Connecting-IP` *before* enabling proxying for real
users.

### 2. certbot HTTP-01 renewal will break

Let's Encrypt's HTTP-01 challenge originates from Let's Encrypt servers, not
Cloudflare. Once the origin firewall is locked to Cloudflare ranges
(Phase 4), LE can no longer reach `/.well-known/acme-challenge/`, and renewal
fails ~60 days later. **Phase 3 fixes this** by switching to a Cloudflare
Origin Certificate (15-year validity, only trusted by Cloudflare) and retiring
certbot.

---

## Phase 1 — Add the domain to Cloudflare (no origin changes)

**Risk:** very low. Site keeps working through Cloudflare with default SSL mode.

1. Sign up / log in at [cloudflare.com](https://cloudflare.com).
2. **Add a site** → enter `qadam.edu.kz`. Pick the Free plan (sufficient for
   this use case; can upgrade later if you want full WAF managed rulesets).
3. Cloudflare scans existing DNS records. **Verify** the `api` A record points
   to `89.35.125.68` (or the current origin IP).
4. At your domain registrar, update the nameservers to the two Cloudflare
   nameservers shown in the dashboard. Wait for activation (usually <1 hour).
5. Once active, in the Cloudflare dashboard DNS panel: ensure the `api` record
   is set to **Proxied** (orange cloud). The `dashboard.qadam.edu.kz` record
   can stay DNS-only (grey) unless you also want to proxy it.

**Verification:**
```bash
dig api.qadam.edu.kz +short
# Should return a Cloudflare IP (e.g. 104.21.x.x or 172.67.x.x), NOT 89.35.125.68
curl -sI https://api.qadam.edu.kz/healthz
# Should return 200, with `cf-ray:` and `server: cloudflare` headers
```

**Rollback:** in DNS panel, toggle the `api` record back to DNS-only (grey
cloud). Traffic bypasses Cloudflare immediately.

---

## Phase 2 — Restore real client IP in nginx

**Risk:** low. Repo change, deployed normally.

Add the following block to `nginx/conf.d/django.conf` (near the top, before
the rate-limit zones):

```nginx
# ── Cloudflare real IP restoration ─────────────────────────────
# Tells nginx that requests proxied by Cloudflare carry the real
# client IP in CF-Connecting-IP. Restores correct rate-limit
# bucketing and access-log client IPs.
# IP ranges from https://www.cloudflare.com/ips/ — refresh quarterly.
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;
real_ip_recursive on;
```

Deploy + reload nginx:
```bash
git pull
docker compose exec nginx nginx -t           # MUST pass
docker compose exec nginx nginx -s reload
```

**Verification:**
```bash
# Make a request through Cloudflare and confirm nginx logs see real client IP,
# not a Cloudflare IP:
docker compose logs --tail=50 nginx | grep <your-public-IP>
```

**Quarterly maintenance:** Cloudflare publishes IP ranges at
[cloudflare.com/ips](https://www.cloudflare.com/ips/). The list rarely
changes, but refresh the `set_real_ip_from` block once a quarter.

---

## Phase 3 — Switch TLS to Cloudflare Origin Certificate

**Risk:** medium. Mishandled certs break HTTPS. Do this in a maintenance window
or have a quick rollback path ready (Phase 1 toggle).

1. **Generate the origin cert in Cloudflare:**
   - Dashboard → SSL/TLS → **Origin Server** → **Create Certificate**.
   - Key type: RSA (2048) or ECDSA (P-256). RSA is widely compatible.
   - Hostnames: `api.qadam.edu.kz` (or `*.qadam.edu.kz` if you want one cert
     to cover everything).
   - Validity: 15 years.
   - Click Create. **Copy the certificate AND the private key now** — the
     private key is shown only once.

2. **Install on the origin server:**
   ```bash
   sudo mkdir -p /etc/ssl/cloudflare
   sudo nano /etc/ssl/cloudflare/api.qadam.edu.kz.pem      # paste cert
   sudo nano /etc/ssl/cloudflare/api.qadam.edu.kz.key      # paste key
   sudo chmod 600 /etc/ssl/cloudflare/*.key
   sudo chmod 644 /etc/ssl/cloudflare/*.pem
   ```

3. **Mount the cert into the nginx container.** In `docker-compose.yml`,
   nginx service, add a volume:
   ```yaml
       volumes:
         # … existing volumes …
         - /etc/ssl/cloudflare:/etc/ssl/cloudflare:ro
   ```

4. **Update `nginx/conf.d/django.conf`** to point at the new cert (in the 443
   server block):
   ```nginx
   ssl_certificate     /etc/ssl/cloudflare/api.qadam.edu.kz.pem;
   ssl_certificate_key /etc/ssl/cloudflare/api.qadam.edu.kz.key;
   ```
   (Replaces the `letsencrypt/live/...` paths.)

5. **In Cloudflare** → SSL/TLS → **Overview**, set encryption mode to
   **Full (strict)**. This forces CF to validate the origin cert.

6. Deploy and reload:
   ```bash
   git pull
   docker compose up -d nginx
   docker compose exec nginx nginx -t
   docker compose exec nginx nginx -s reload
   ```

7. **Verification:**
   ```bash
   curl -sI https://api.qadam.edu.kz/healthz       # 200
   # Direct origin check (before Phase 4 lockdown):
   curl -skI --resolve api.qadam.edu.kz:443:<origin-ip> https://api.qadam.edu.kz/healthz
   # Should return 200 and the cert subject should be Cloudflare's Origin CA.
   ```

8. **Retire certbot** (after confirming HTTPS works end-to-end):
   - Remove the `certbot` service block from `docker-compose.yml`.
   - Optional: remove `nginx/conf.d/certonly.conf` (no longer needed).
   - Keep the Let's Encrypt certs on disk as a fallback for a few days.

**Rollback:** point `ssl_certificate`/`ssl_certificate_key` back to the
Let's Encrypt paths and `nginx -s reload`. In Cloudflare, set SSL mode back to
**Full** (not strict) temporarily.

---

## Phase 4 — Lock the origin firewall to Cloudflare-only

**This is the phase that actually stops bypass.** Until you do this, attackers
who know the raw IP can still reach the origin directly. Cloudflare's protections
are bypassed.

**Risk:** if misconfigured, you lock yourself out. **Test from an outside
network**, and keep an SSH session open as a backup.

Pick one based on your hosting:

### Option A — `ufw` (Ubuntu/Debian VPS)

```bash
# Reset existing rules (DANGER: keep SSH open via separate rule first)
sudo ufw allow 22/tcp                            # KEEP SSH

# Allow only Cloudflare to reach 80/443
for cidr in $(curl -s https://www.cloudflare.com/ips-v4); do
  sudo ufw allow from $cidr to any port 443 proto tcp
  sudo ufw allow from $cidr to any port 80 proto tcp
done
for cidr in $(curl -s https://www.cloudflare.com/ips-v6); do
  sudo ufw allow from $cidr to any port 443 proto tcp
  sudo ufw allow from $cidr to any port 80 proto tcp
done

sudo ufw default deny incoming
sudo ufw enable
sudo ufw status verbose
```

### Option B — Cloud provider security group (AWS / GCP / Azure / Hetzner)

In your cloud console, edit the security group / firewall attached to the
origin VM:
- Inbound 443 (and 80): **source = Cloudflare IPv4 + IPv6 ranges only**.
- Inbound 22: source = your office/admin IP only.
- Everything else: deny.

Most cloud consoles accept multiple CIDR entries — paste the Cloudflare lists.

### Option C — `iptables` (any Linux)

```bash
# Backup current rules
sudo iptables-save > /root/iptables.backup

# Flush INPUT (DANGER: have SSH access via console as fallback)
sudo iptables -F INPUT
sudo iptables -P INPUT DROP

# Always allow loopback + established + SSH
sudo iptables -A INPUT -i lo -j ACCEPT
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT

# Allow Cloudflare to 80/443
for cidr in $(curl -s https://www.cloudflare.com/ips-v4); do
  sudo iptables -A INPUT -p tcp -s $cidr --dport 443 -j ACCEPT
  sudo iptables -A INPUT -p tcp -s $cidr --dport 80 -j ACCEPT
done

# Persist (Debian/Ubuntu)
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

### Verification (from a network NOT behind Cloudflare)

```bash
# Direct origin IP — should hang or time out:
curl -v --connect-timeout 5 https://89.35.125.68/

# Through Cloudflare — should return 200:
curl -sI https://api.qadam.edu.kz/healthz
```

If direct IP still responds: your firewall didn't apply. If api.qadam.edu.kz
fails: your CIDR list is wrong — `dig api.qadam.edu.kz` to confirm CF IPs
and cross-check.

**Rollback:** `sudo ufw disable` (Option A) or restore the iptables backup
(Option C) or revert the cloud security group changes (Option B).

---

## Phase 5 — Enable Cloudflare protections (dashboard)

**Risk:** low. All toggleable, all reversible from the dashboard.

In the Cloudflare dashboard for `qadam.edu.kz`:

### Security → WAF
- **Managed Rules** → enable **Cloudflare Managed Ruleset** (OWASP Core).
- **Custom Rules** → add a "challenge" rule for known-bad signatures (e.g.
  block any request whose URL path matches
  `/(wp-admin|wp-login|vendor/phpunit|\.env|\.git)/i`).

### Security → Bots
- **Bot Fight Mode** → ON.
- **Verified Bots** → review and allow (e.g. Googlebot, Uptime Robot if you
  use it).

### Security → Rate Limiting Rules
Add an edge-level layer above nginx rate limits:
- **Login endpoint**: 10 requests / 1 minute per IP on path
  `/api/v1/auth/login/`, action: Block, duration: 10m.
- **Admin endpoint**: 60 requests / 1 minute per IP on path `/admin/`,
  action: Challenge.

### SSL/TLS → Edge Certificates
- **Always Use HTTPS** → ON.
- **Minimum TLS Version** → 1.2 (you've already set this at origin).
- **Automatic HTTPS Rewrites** → ON.
- **HSTS** → leave OFF here. Django already emits HSTS with 2-year max-age
  and preload. Setting it at both layers risks conflicting values.

### Speed → Optimization
- **Auto Minify** → off for JSON/HTML (interferes with API responses); CSS/JS
  can be on if you ever serve static assets through CF.
- **Brotli** → ON.

### Caching → Configuration
- For an API, set **Caching Level** to "No query string" or use a Page Rule
  to bypass cache on `/api/*` entirely (you do NOT want CF to cache
  authenticated API responses).

---

## End-to-end verification checklist

```bash
# 1. DNS now goes to Cloudflare
dig api.qadam.edu.kz +short
# → Cloudflare IPs, not 89.35.125.68

# 2. HTTPS works through CF
curl -sI https://api.qadam.edu.kz/healthz
# → HTTP/2 200, headers include `cf-ray:` and `server: cloudflare`

# 3. Origin IP cannot be hit directly
curl -v --connect-timeout 5 https://89.35.125.68/
# → connection timed out / refused

# 4. Real client IP reaches Django (so rate limiting works)
docker compose logs --tail=50 nginx | grep "$(curl -s ifconfig.me)"
# → should appear in access logs

# 5. Origin certificate is the Cloudflare Origin CA (not Let's Encrypt)
echo | openssl s_client -connect 89.35.125.68:443 -servername api.qadam.edu.kz 2>/dev/null \
  | openssl x509 -noout -issuer
# (run from a Cloudflare IP — easier: check via the dashboard SSL panel)

# 6. Swagger still admin-only
curl -sI https://api.qadam.edu.kz/api/docs/
# → 403 (unauthenticated)

# 7. WAF blocks obvious probes
curl -sI 'https://api.qadam.edu.kz/.env'
# → 403 Forbidden from Cloudflare (or 444 from origin)
```

---

## Maintenance

- **Quarterly:** refresh the `set_real_ip_from` CIDR list in nginx from
  [cloudflare.com/ips](https://www.cloudflare.com/ips/).
- **Quarterly:** refresh the firewall rules with the latest CF ranges.
- **Annually:** review WAF rule hits in the Cloudflare Security dashboard;
  tune custom rules based on observed traffic.
- **Origin cert expiry:** 15 years from creation. Set a calendar reminder.

---

## Rollback (full)

If anything goes wrong at any phase, the safest rollback is:

1. In Cloudflare DNS panel, toggle the `api` record to **DNS-only (grey
   cloud)** → traffic bypasses Cloudflare immediately.
2. If the firewall was locked down (Phase 4), open `:80` and `:443` to all
   sources again (`sudo ufw delete` rules, or restore iptables backup).
3. Revert nginx `ssl_certificate` paths to Let's Encrypt (Phase 3 rollback).
4. Re-enable the `certbot` compose service if removed.

The site is back on direct DNS to the origin with the original cert and
firewall.
