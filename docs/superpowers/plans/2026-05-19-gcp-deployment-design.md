# Design: TradingAgents production deployment to `tradix.axiara.ai`

**Date:** 2026-05-19
**Status:** Approved (design) — implementation plan to follow
**Owner:** erikgunawans
**Related:** Closes the "🚀 Cloud + VPS deployment (active)" item in `PROGRESS.md` (What To Do Next)

---

## 1. Context

Today TradingAgents only runs locally via `docker compose up`. There is no public deployment of the dashboard. The user (Erik) wants to be able to demo the system to a small group via a real domain and HTTPS, while keeping the deploy artifact portable enough to move to a different VPS later if cost or jurisdiction changes.

The chosen target is **a single GCP Compute Engine VM running the existing `docker-compose.yml` stack**. The same compose file remains valid on any VPS (Hetzner, DigitalOcean, Linode, etc.) so portability is preserved by construction: there is no managed-services lock-in.

## 2. Goals

- `https://tradix.axiara.ai` resolves to the production dashboard with a valid HTTPS cert.
- Sign-in via the existing GitHub OAuth app works in production.
- Worker can run a TradingAgents analysis end-to-end (subject to the LLM-provider quota, which is account-level and out of scope).
- Updates ship from `main` automatically: `git push` → live in ~3 minutes.
- Daily Postgres + reports backups land in a GCS bucket and survive VM loss.
- The deploy artifact (compose files + Caddyfile + env contract) remains VPS-portable — moving to Hetzner later means `scp` the same files and re-run the bootstrap script.

## 3. Non-goals

- Autoscaling — single VM, vertical scaling only via `gcloud compute instances stop && resize && start`.
- Multi-region failover — single zone (`asia-southeast2-a`).
- Blue-green or zero-downtime deploys — a few seconds of unavailability during `docker compose up -d` is acceptable at this scale.
- Multi-tenant isolation — every user shares the same DB + worker queue.
- Light-mode UI variant, `_persist_reports` worker refactor, or library test infrastructure cleanup — those remain separate "What To Do Next" items.
- Cloudflare / CDN / WAF in front — optional add-on noted in §11, not part of v1.
- Observability beyond GCP's default VM metrics — no log aggregation, no APM, no Sentry yet.
- Managed services (Cloud Run, Cloud SQL, Memorystore, GCS-for-reports) — explicitly rejected during brainstorming in favor of portability.

## 4. Architecture

One GCP Compute Engine VM (`e2-medium`, `asia-southeast2-a`, 4 GB RAM, 30 GB pd-balanced disk) runs the entire stack via the existing `docker-compose.yml` plus a new `docker-compose.prod.yml` overlay. Caddy is the only service that publishes ports to the host; every other service is reachable only on the internal docker network.

```
                     ┌────────────────────────────────────────────────┐
   Internet ──443──► │  caddy  (Let's Encrypt auto-cert, :80 + :443) │
                     │   │                                            │
                     │   └─► web (Next.js, :3000 internal)            │
                     │         └─► api (FastAPI, :8000 internal)      │
                     │               ├─► db (Postgres 16, internal)   │
                     │               └─► redis (internal)             │
                     │                          ▲                     │
                     │                          │                     │
                     │   worker (arq) ──────────┘                     │
                     │     │                                          │
                     │     └─writes─► /data (named volume)            │
                     │                  ▲                             │
                     │                  └─reads─ api                  │
                     └────────────────────────────────────────────────┘
                                       │
                                       ▼ daily 03:00 ICT
                              gs://tradix-backups/  (14d lifecycle)
```

**Public surface:** `https://tradix.axiara.ai` (port 443) + SSH (port 22, restricted). Nothing else.

**Internal-only services:** `db`, `redis`, `api`, `web`, `worker`. None of these have `ports:` mappings in `docker-compose.prod.yml` — they communicate over the docker network via service-name DNS.

**Shared state:** the `dashdata` named volume is mounted into both `api` (read) and `worker` (read+write). This is preserved as-is from the dev compose file — no GCS refactor needed because we chose the single-VM topology.

## 5. Infrastructure provisioning

One-time, manual, scripted as `infra/provision.sh` (idempotent):

1. **VM**: `e2-medium` in `asia-southeast2-a`. Image: `debian-12`. Disk: 30 GB pd-balanced. Reserved static external IP.
2. **Firewall**: allow tcp:22 (SSH), tcp:80 (HTTP→HTTPS redirect + Let's Encrypt challenge), tcp:443 (HTTPS). Deny all other inbound. SSH source range optionally restricted to the user's IP.
3. **DNS** (Hostinger DNS Zone Editor for `axiara.ai`): A record `tradix → <static-ip>`, TTL 300. Confirm with `dig tradix.axiara.ai`.
4. **GCS bucket**: `gs://tradix-backups`, location `asia-southeast2`, standard storage class, lifecycle rule "delete after 14 days" applied to all objects.
5. **Service account**: `tradix-vm@<project>.iam.gserviceaccount.com`, role `roles/storage.objectAdmin` scoped to the backup bucket only (not project-wide). Attached to the VM via `gcloud compute instances set-service-account`. The backup cron uses `gcloud` with the VM's metadata-server identity — no long-lived JSON keys on disk.
6. **GitHub OAuth app**: add `https://tradix.axiara.ai/api/auth/callback/github` to the existing OAuth app's callback whitelist (alongside the existing localhost callback). One app, two callbacks.

**Bootstrap on the VM** (`infra/bootstrap.sh`, run via `gcloud compute ssh` once):

- Install Docker Engine + Docker Compose plugin (apt repo, not Snap).
- Install `gcloud` CLI (already available on GCP Debian images, but verify).
- `mkdir -p /srv/tradingagents /etc/tradingagents`
- `git clone https://github.com/erikgunawans/TradingAgents.git /srv/tradingagents`
- Place the prod `.env` file at `/etc/tradingagents/env`, mode 0600, owned by root.
- Install the backup script (`/usr/local/bin/tradix-backup.sh`) + cron entry (`/etc/cron.d/tradix-backup`).
- `cd /srv/tradingagents && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

## 6. Reverse proxy + HTTPS

A new `caddy` service is added in `docker-compose.prod.yml`:

```yaml
caddy:
  image: caddy:2-alpine
  restart: unless-stopped
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./Caddyfile:/etc/caddy/Caddyfile:ro
    - caddy_data:/data
    - caddy_config:/config
  depends_on:
    - web
```

`Caddyfile` (committed to repo root):

```caddyfile
tradix.axiara.ai {
    encode gzip zstd
    reverse_proxy web:3000
}
```

Caddy auto-fetches a Let's Encrypt cert on first start (HTTP-01 challenge over port 80) and auto-renews. The `caddy_data` named volume persists certs across container restarts.

**Why Caddy over nginx + certbot**: one-file config, no certbot reload hooks, no cron job for renewal, native docker-compose integration. For a single-app reverse proxy this is purely upside.

## 7. Image build + deploy pipeline

**Trigger:** push to `main` on `github.com/erikgunawans/TradingAgents`.

**Workflow file:** `.github/workflows/deploy.yml`.

### Build job (parallel matrix, ~2 min)

```
matrix: [api, web]
  - docker buildx build with --platform=linux/amd64
  - tag: ghcr.io/erikgunawans/tradingagents-${service}:${GITHUB_SHA}
  - tag: ghcr.io/erikgunawans/tradingagents-${service}:latest
  - push both tags
```

Authentication to ghcr.io uses the workflow's `GITHUB_TOKEN` with `packages: write` permission. No external secrets needed for the registry side.

### Deploy job (depends on build, ~30 sec)

```
1. SSH to VM (key from GitHub Secrets DEPLOY_SSH_KEY)
2. cd /srv/tradingagents
3. git pull --ff-only
4. docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
5. docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
6. docker image prune -f
```

The `git pull` is for Caddyfile + compose overlay changes (not for source — source lives in the published images).

### `docker-compose.prod.yml` overlay

Replaces `build:` blocks with `image:` refs. Image tags resolve from an `IMAGE_TAG` env var so rollback can pin to any prior SHA without editing the compose file:

```yaml
services:
  api:
    image: ghcr.io/erikgunawans/tradingagents-api:${IMAGE_TAG:-latest}
    pull_policy: always
    build: !reset null
    env_file: /etc/tradingagents/env
    ports: !override []           # private, Caddy reaches via docker net
  worker:
    image: ghcr.io/erikgunawans/tradingagents-api:${IMAGE_TAG:-latest}   # same image, different command
    pull_policy: always
    build: !reset null
    env_file: /etc/tradingagents/env
  web:
    image: ghcr.io/erikgunawans/tradingagents-web:${IMAGE_TAG:-latest}
    pull_policy: always
    build: !reset null
    env_file: /etc/tradingagents/env
    ports: !override []
  db:
    ports: !override []
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}    # generated, not the literal "trading"
  redis:
    ports: !override []
  caddy:
    # (defined in §6)
```

The GitHub Actions deploy step exports `IMAGE_TAG=${GITHUB_SHA}` over the SSH connection before running `docker compose up`. The current SHA is also written to `/srv/tradingagents/.current_image_tag` on each deploy so a human can read it back.

### Rollback

```
ssh vm
cat /srv/tradingagents/.current_image_tag        # confirm current
IMAGE_TAG=<prev-sha> docker compose \
  -f /srv/tradingagents/docker-compose.yml \
  -f /srv/tradingagents/docker-compose.prod.yml \
  pull
IMAGE_TAG=<prev-sha> docker compose \
  -f /srv/tradingagents/docker-compose.yml \
  -f /srv/tradingagents/docker-compose.prod.yml \
  up -d
echo <prev-sha> > /srv/tradingagents/.current_image_tag
```

Image tags pin to `${GITHUB_SHA}` on every push (in addition to a moving `:latest`), so any prior version is one command away. Rollback runbook is `docs/runbooks/rollback.md`.

## 8. Secrets management

**Location:** `/etc/tradingagents/env` on the VM. Owner `root:root`, mode `0600`. Not in git.

**Loading:** every service in `docker-compose.prod.yml` references `env_file: /etc/tradingagents/env`. Docker compose reads it at `up` time and injects vars into the container env.

**Required contents:**

```bash
# NextAuth
NEXTAUTH_SECRET=<openssl rand -hex 32>
NEXTAUTH_URL=https://tradix.axiara.ai

# GitHub OAuth (from the OAuth app's settings page)
AUTH_GITHUB_ID=<client id>
AUTH_GITHUB_SECRET=<client secret>

# Postgres
POSTGRES_PASSWORD=<openssl rand -hex 24>
DATABASE_URL=postgresql+asyncpg://trading:${POSTGRES_PASSWORD}@db:5432/trading_dashboard

# LLM providers (at least one must work)
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=...

# Worker model defaults (override .env.example values)
DEFAULT_LLM_PROVIDER=openrouter           # or whichever provider has working quota
DEFAULT_DEEP_THINK_LLM=anthropic/claude-3.5-sonnet
DEFAULT_QUICK_THINK_LLM=openai/gpt-4o-mini
```

**Why not Google Secret Manager:** would lock the design to GCP and break the "single portable artifact" promise. Moving to Hetzner later would mean replacing the secrets layer, not just `scp`-ing one file.

**First-boot sequence** (`docs/runbooks/first-boot.md`):
1. Generate `NEXTAUTH_SECRET` + `POSTGRES_PASSWORD`.
2. Write `/etc/tradingagents/env` with all values above.
3. Bring up the stack: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
4. Postgres seeds the `trading` user with the new `POSTGRES_PASSWORD` on **first ever boot only** — if the `dbdata` volume already exists with a different password, the env var is ignored and you have to either reset the volume or manually `ALTER USER`. The runbook documents this gotcha explicitly.
5. Verify `https://tradix.axiara.ai` resolves with a valid cert, GitHub sign-in works, and a test analysis run completes.

## 9. Backups

**What:** Postgres dump (gzipped) + `dashdata` volume tarball.

**When:** daily at 03:00 Asia/Jakarta time. Cron: `/etc/cron.d/tradix-backup`.

**Where:** `gs://tradix-backups/db/` and `gs://tradix-backups/reports/`. 14-day retention enforced by a GCS object lifecycle rule (not by the script — the script never deletes).

**Script** (`/usr/local/bin/tradix-backup.sh`):

```bash
#!/bin/bash
set -euo pipefail
TS=$(date +%Y%m%d-%H%M%S)
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

docker exec -t $(docker ps -qf name=db) \
  pg_dump -U trading trading_dashboard | gzip > "$TMPDIR/db-${TS}.sql.gz"

docker run --rm \
  -v tradingagents_dashdata:/data:ro \
  -v "$TMPDIR":/backup \
  alpine tar -czf /backup/reports-${TS}.tgz -C /data .

gcloud storage cp "$TMPDIR/db-${TS}.sql.gz"      gs://tradix-backups/db/
gcloud storage cp "$TMPDIR/reports-${TS}.tgz"    gs://tradix-backups/reports/
```

**Restore** (`docs/runbooks/restore-from-backup.md`):
1. `gcloud storage cp gs://tradix-backups/db/<filename> .`
2. `gunzip <filename> | docker exec -i <db-container> psql -U trading trading_dashboard`
3. For reports: `gcloud storage cp ... && docker run --rm -v tradingagents_dashdata:/data ... tar -xzf ...`.

**Tested during rollout**, not just documented — the implementation plan includes a "restore from yesterday's backup into a scratch DB" verification step.

**Cost:** at this volume (<100 MB combined per day × 14 days = <1.5 GB total residency), well under $0.10/mo.

## 10. Repository changes summary

New files:

- `Caddyfile`
- `docker-compose.prod.yml`
- `.github/workflows/deploy.yml`
- `infra/provision.sh` — GCP one-time setup (idempotent)
- `infra/bootstrap.sh` — VM-side one-time setup
- `scripts/tradix-backup.sh` — installed to `/usr/local/bin/` by bootstrap
- `docs/runbooks/first-boot.md`
- `docs/runbooks/rollback.md`
- `docs/runbooks/restore-from-backup.md`
- `docs/deployment.md` — index pointing at the runbooks + an architecture summary

Modified files:

- `docker-compose.yml` — no functional changes; current dev shape is preserved. The prod overlay handles all prod-specific differences.
- `.env.example` — add `POSTGRES_PASSWORD` placeholder + comments referencing the runbook.
- `PROGRESS.md` — checkpoint section once the deploy lands.
- `README.md` — short "Production deployment" pointer to `docs/deployment.md`.

## 11. Open questions

1. **LLM provider for prod default.** PROGRESS.md notes the OpenAI account is at 429 quota. Which provider should `DEFAULT_LLM_PROVIDER` be set to on first boot? Likely OpenRouter (works as a multi-model gateway), but confirm before provisioning.
2. **Existing GitHub OAuth app.** Confirm the OAuth app's ID + secret are already known and you have admin access to add the new callback URL.
3. **Cloudflare in front.** Optional add-on (free tier — DDoS, basic WAF, geographic blocking, edge cache). Not blocking and easily added later by switching the Hostinger A record to a CNAME pointing at Cloudflare. Decision can be deferred until after first deploy is stable.
4. **SSH access policy.** Should the firewall restrict tcp:22 to your IP only, or accept SSH from anywhere (relying on key-only auth + fail2ban)? Defaults to "anywhere + key-only" unless you say otherwise.

## 12. Acceptance criteria

The implementation plan (separate doc) is complete when all of these are true:

- [ ] `https://tradix.axiara.ai` returns the dashboard with a valid Let's Encrypt cert.
- [ ] GitHub OAuth sign-in completes successfully end-to-end.
- [ ] A test analysis run (e.g., `BBCA.JK` to exercise the new IDX path) reaches at least the LLM API call stage in the worker log stream.
- [ ] `git push origin main` from a clean source change ships the change to production in <5 minutes with no manual steps.
- [ ] `gs://tradix-backups/db/` contains at least one `pg_dump` artifact and one reports tarball within 24h of the first deploy.
- [ ] A restore-into-scratch-DB drill from a backup artifact succeeds.
- [ ] No public ports exposed beyond 22 / 80 / 443.
- [ ] The same `docker-compose.yml` (without `docker-compose.prod.yml`) still works locally for dev — no regression in the local-dev experience.
