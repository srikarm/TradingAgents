# GCP Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `https://tradix.axiara.ai` serve the TradingAgents dashboard from a single GCP Compute Engine VM, with automated `main` → live deploys via GitHub Actions and daily off-VM backups to GCS.

**Architecture:** One `e2-medium` VM in `asia-southeast2-a` runs the existing `docker-compose.yml` stack plus a new `docker-compose.prod.yml` overlay. Caddy is the only service exposed to the public internet (terminates TLS via Let's Encrypt, reverse-proxies to `web`). All other services are private on the docker network. Images are built in GitHub Actions, pushed to ghcr.io, and pulled by the VM on deploy. Daily cron uploads Postgres dumps + reports tarballs to a GCS bucket with a 14-day lifecycle rule.

**Tech Stack:** Docker Compose v2, Caddy 2 (Alpine), GitHub Actions, GitHub Container Registry (ghcr.io), GCP Compute Engine + Cloud Storage + IAM, OpenSSH + fail2ban, OpenRouter as the prod LLM gateway.

**Spec:** [`docs/superpowers/plans/2026-05-19-gcp-deployment-design.md`](./2026-05-19-gcp-deployment-design.md)

---

## Before You Start

This plan assumes you can answer "yes" to all of these:

- You have a GCP account with billing enabled and `gcloud` CLI installed + authenticated (`gcloud auth login`).
- You have admin on `github.com/erikgunawans/TradingAgents` and on the existing GitHub OAuth app used by NextAuth.
- You can edit DNS records for `axiara.ai` in Hostinger's DNS Zone Editor.
- You have an OpenRouter account with credit and an API key ready.
- You have a local clone of `TradingAgents` and `docker compose` installed locally.

### Variables to set in your shell (do this once at the start of each session)

```bash
# GCP
export GCP_PROJECT_ID="your-project-id"          # gcloud config get-value project
export GCP_REGION="asia-southeast2"
export GCP_ZONE="asia-southeast2-a"
export VM_NAME="tradix"
export STATIC_IP_NAME="tradix-ip"
export BUCKET_NAME="tradix-backups"
export SA_NAME="tradix-vm"

# Domain
export DOMAIN="tradix.axiara.ai"
export FORK_REPO="erikgunawans/TradingAgents"     # GitHub repo path

gcloud config set project "$GCP_PROJECT_ID"
```

Save this block into `~/.tradix-deploy-env` and `source ~/.tradix-deploy-env` at the start of each session.

---

## Phase 1 — Local repo changes (no cloud touched)

### Task 1: Create the feature branch

**Files:** none (git operation only).

- [ ] **Step 1: Make sure you are on `main` and synced**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git fetch fork
git checkout main
git pull fork main
```

Expected: `Already up to date.` or fast-forward to `0274ddd` (the design-doc commit).

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b feature/gcp-deploy
```

Expected: `Switched to a new branch 'feature/gcp-deploy'`.

---

### Task 2: Add the production compose overlay

**Files:**
- Create: `docker-compose.prod.yml`

- [ ] **Step 1: Write `docker-compose.prod.yml`**

```yaml
# Production overlay. Used with:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
#
# Overrides the dev compose to:
#   - replace `build:` with pre-built ghcr.io images (built by CI)
#   - hide internal services from the host (no public ports for db/redis/api/web)
#   - load secrets from /etc/tradingagents/env (NOT in git)
#   - add Caddy reverse proxy as the only public-facing service
#   - use a generated POSTGRES_PASSWORD instead of the dev literal "trading"

services:
  api:
    image: ghcr.io/erikgunawans/tradingagents-api:${IMAGE_TAG:-latest}
    pull_policy: always
    build: !reset null
    env_file: /etc/tradingagents/env
    ports: !override []

  worker:
    image: ghcr.io/erikgunawans/tradingagents-api:${IMAGE_TAG:-latest}
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
      POSTGRES_USER: trading
      POSTGRES_DB: trading_dashboard
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  redis:
    ports: !override []

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

volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 2: Verify YAML is well-formed**

```bash
python3 -c "import yaml; yaml.safe_load(open('docker-compose.prod.yml'))"
```

Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "chore(deploy): add docker-compose.prod.yml overlay for production"
```

---

### Task 3: Add the Caddyfile

**Files:**
- Create: `Caddyfile`

- [ ] **Step 1: Write `Caddyfile`**

```caddyfile
# Production reverse proxy for tradix.axiara.ai.
# Caddy auto-fetches + auto-renews a Let's Encrypt cert on first start.

tradix.axiara.ai {
    encode gzip zstd
    reverse_proxy web:3000

    # Forward client IP to upstream — Next.js + FastAPI both honor X-Forwarded-For
    # via the standard headers Caddy sets by default.
}
```

- [ ] **Step 2: Lint with the Caddy image (no Caddy install required locally)**

```bash
docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine \
  caddy validate --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration` on the last line.

- [ ] **Step 3: Commit**

```bash
git add Caddyfile
git commit -m "chore(deploy): add Caddyfile reverse proxy config"
```

---

### Task 4: Add the secret-generation helper and update `.env.example`

**Files:**
- Create: `scripts/gen-prod-env.sh`
- Modify: `.env.example`

- [ ] **Step 1: Write `scripts/gen-prod-env.sh`**

```bash
#!/usr/bin/env bash
# Generates a starting /etc/tradingagents/env file for a prod VM.
# Prints to stdout — you redirect / scp / cat-paste it to the VM yourself.
# Re-running generates fresh secrets; the OUTPUT is the only state.

set -euo pipefail

NEXTAUTH_SECRET="$(openssl rand -hex 32)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"

cat <<EOF
# Production env for tradix.axiara.ai
# Generated by scripts/gen-prod-env.sh — review every value before deploying.
# Place at /etc/tradingagents/env on the VM (chmod 600, root:root).

# NextAuth
NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
NEXTAUTH_URL=https://tradix.axiara.ai

# GitHub OAuth (paste from the OAuth app's settings page)
AUTH_GITHUB_ID=PASTE_FROM_GITHUB_OAUTH_APP
AUTH_GITHUB_SECRET=PASTE_FROM_GITHUB_OAUTH_APP

# Postgres — POSTGRES_PASSWORD only honored on first DB init (empty volume).
# If the dbdata volume already exists with a different password, you must
# either docker volume rm tradingagents_dbdata (loses data) or ALTER USER
# manually inside the running db container. See docs/runbooks/first-boot.md.
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=postgresql+asyncpg://trading:${POSTGRES_PASSWORD}@db:5432/trading_dashboard

# LLM providers — at least one must work end-to-end.
# OpenRouter is the prod default (multi-model gateway, one key).
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
OPENROUTER_API_KEY=PASTE_FROM_OPENROUTER_DASHBOARD

# Worker model defaults
DEFAULT_LLM_PROVIDER=openrouter
DEFAULT_DEEP_THINK_LLM=anthropic/claude-3.5-sonnet
DEFAULT_QUICK_THINK_LLM=openai/gpt-4o-mini
EOF
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/gen-prod-env.sh
```

- [ ] **Step 3: Smoke-test the generator**

```bash
./scripts/gen-prod-env.sh | head -5
```

Expected: header comments + a `NEXTAUTH_SECRET=` line with a 64-char hex value.

- [ ] **Step 4: Update `.env.example`** — add a `POSTGRES_PASSWORD` placeholder and a pointer to the runbook.

Append to `.env.example`:

```
# Postgres — only required for production (dev defaults to "trading:trading").
# Generate with: openssl rand -hex 24
# See docs/runbooks/first-boot.md for the first-init gotcha.
POSTGRES_PASSWORD=
```

- [ ] **Step 5: Commit**

```bash
git add scripts/gen-prod-env.sh .env.example
git commit -m "chore(deploy): add scripts/gen-prod-env.sh + POSTGRES_PASSWORD in .env.example"
```

---

### Task 5: Validate the prod overlay against the dev compose locally

Goal: confirm `docker-compose.yml + docker-compose.prod.yml` merges to a valid spec before we get anywhere near GCP.

**Files:** none (verification only).

- [ ] **Step 1: Set placeholder env vars + run `docker compose config`**

```bash
IMAGE_TAG=latest \
POSTGRES_PASSWORD=local-test-only \
docker compose -f docker-compose.yml -f docker-compose.prod.yml config > /tmp/merged.yml
```

Expected: exits 0, `/tmp/merged.yml` is a fully-resolved compose spec.

- [ ] **Step 2: Confirm the merge produced what we want**

```bash
# No public ports on db / redis / api / web
grep -A2 '^  db:' /tmp/merged.yml   | grep -q 'published' && echo "FAIL: db has port" || echo "OK: db private"
grep -A2 '^  redis:' /tmp/merged.yml | grep -q 'published' && echo "FAIL: redis has port" || echo "OK: redis private"
grep -A2 '^  api:' /tmp/merged.yml  | grep -q 'published' && echo "FAIL: api has port" || echo "OK: api private"
grep -A2 '^  web:' /tmp/merged.yml  | grep -q 'published' && echo "FAIL: web has port" || echo "OK: web private"

# Caddy is the only service publishing ports
grep -B1 '^      published:' /tmp/merged.yml | grep -B1 ': "80"\|: "443"' | head
```

Expected: 4 × `OK:` lines + Caddy is the only service with `published: "80"` / `"443"`.

- [ ] **Step 3: Confirm worker shares the api image**

```bash
grep -E '^  (api|worker):|image:' /tmp/merged.yml | grep -A1 -E '^  (api|worker):'
```

Expected: both `api` and `worker` reference `ghcr.io/erikgunawans/tradingagents-api:latest`.

No commit — this task is verification only.

---

### Task 6: Add the GCP provisioning script

**Files:**
- Create: `infra/provision.sh`

- [ ] **Step 1: Create the `infra/` directory and write `infra/provision.sh`**

```bash
mkdir -p infra
```

Then write `infra/provision.sh`:

```bash
#!/usr/bin/env bash
# Idempotent GCP one-time provisioning for tradix.axiara.ai.
# Requires gcloud CLI authenticated + the env vars listed in
# docs/superpowers/plans/2026-05-19-gcp-deployment-plan.md ("Before You Start").

set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_REGION:?Set GCP_REGION}"
: "${GCP_ZONE:?Set GCP_ZONE}"
: "${VM_NAME:?Set VM_NAME}"
: "${STATIC_IP_NAME:?Set STATIC_IP_NAME}"
: "${BUCKET_NAME:?Set BUCKET_NAME}"
: "${SA_NAME:?Set SA_NAME}"

gcloud config set project "$GCP_PROJECT_ID"

echo "==> Enabling required APIs (idempotent)"
gcloud services enable compute.googleapis.com storage.googleapis.com

echo "==> Reserving static external IP $STATIC_IP_NAME (if missing)"
if ! gcloud compute addresses describe "$STATIC_IP_NAME" --region "$GCP_REGION" >/dev/null 2>&1; then
  gcloud compute addresses create "$STATIC_IP_NAME" --region "$GCP_REGION"
fi
STATIC_IP=$(gcloud compute addresses describe "$STATIC_IP_NAME" --region "$GCP_REGION" --format='value(address)')
echo "    Static IP: $STATIC_IP"

echo "==> Creating service account $SA_NAME (if missing)"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name "Tradix VM service account"
fi

echo "==> Creating GCS bucket gs://$BUCKET_NAME (if missing)"
if ! gcloud storage buckets describe "gs://$BUCKET_NAME" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET_NAME" --location="$GCP_REGION" --uniform-bucket-level-access
fi

echo "==> Applying 14-day lifecycle rule to gs://$BUCKET_NAME"
cat >/tmp/lifecycle.json <<'JSON'
{
  "rule": [
    { "action": {"type": "Delete"}, "condition": {"age": 14} }
  ]
}
JSON
gcloud storage buckets update "gs://$BUCKET_NAME" --lifecycle-file=/tmp/lifecycle.json
rm /tmp/lifecycle.json

echo "==> Granting service account objectAdmin on the backup bucket only"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin" >/dev/null

echo "==> Creating firewall rules (idempotent)"
for rule in tradix-allow-ssh:tcp:22 tradix-allow-http:tcp:80 tradix-allow-https:tcp:443; do
  name="${rule%%:*}"
  proto_port="${rule#*:}"
  proto="${proto_port%:*}"
  port="${proto_port#*:}"
  if ! gcloud compute firewall-rules describe "$name" >/dev/null 2>&1; then
    gcloud compute firewall-rules create "$name" \
      --network=default --direction=INGRESS --action=ALLOW \
      --rules="${proto}:${port}" --source-ranges=0.0.0.0/0 \
      --target-tags=tradix
  fi
done

echo "==> Creating VM $VM_NAME (if missing)"
if ! gcloud compute instances describe "$VM_NAME" --zone "$GCP_ZONE" >/dev/null 2>&1; then
  gcloud compute instances create "$VM_NAME" \
    --zone="$GCP_ZONE" \
    --machine-type=e2-medium \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-balanced \
    --address="$STATIC_IP" \
    --service-account="$SA_EMAIL" \
    --scopes=cloud-platform \
    --tags=tradix
fi

echo "==> Done."
echo ""
echo "Static IP:        $STATIC_IP"
echo "VM:               ${VM_NAME} in ${GCP_ZONE}"
echo "Service account:  ${SA_EMAIL}"
echo "Backup bucket:    gs://${BUCKET_NAME}"
echo ""
echo "Next: point Hostinger DNS A record for tradix.axiara.ai at $STATIC_IP."
```

- [ ] **Step 2: Make it executable + lint the syntax**

```bash
chmod +x infra/provision.sh
bash -n infra/provision.sh
```

Expected: no output from `bash -n` (script syntax is valid).

- [ ] **Step 3: Commit**

```bash
git add infra/provision.sh
git commit -m "chore(deploy): add infra/provision.sh (idempotent GCP bootstrap)"
```

---

### Task 7: Add the VM bootstrap script

**Files:**
- Create: `infra/bootstrap.sh`

- [ ] **Step 1: Write `infra/bootstrap.sh`**

```bash
#!/usr/bin/env bash
# Runs ON the VM (not on your laptop). Installs Docker, fail2ban, clones the
# repo to /srv/tradingagents, installs the backup script and cron entry.
#
# Idempotent: re-running should be a no-op once the VM is set up.

set -euo pipefail

FORK_REPO="${FORK_REPO:-erikgunawans/TradingAgents}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

echo "==> Updating apt"
apt-get update -y
apt-get upgrade -y

echo "==> Installing Docker Engine (apt repo, not Snap)"
if ! command -v docker >/dev/null; then
  apt-get install -y ca-certificates curl gnupg lsb-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

echo "==> Installing fail2ban for sshd"
apt-get install -y fail2ban
cat >/etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
port    = 22
maxretry = 5
bantime = 600
EOF
systemctl enable --now fail2ban

echo "==> Disabling password SSH (key-only)"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

echo "==> Cloning repo to /srv/tradingagents"
mkdir -p /srv
if [[ ! -d /srv/tradingagents/.git ]]; then
  git clone "https://github.com/${FORK_REPO}.git" /srv/tradingagents
fi
chown -R root:root /srv/tradingagents

echo "==> Creating /etc/tradingagents/"
mkdir -p /etc/tradingagents
chmod 700 /etc/tradingagents
chown root:root /etc/tradingagents

echo "==> Installing backup script + cron"
install -m 0755 /srv/tradingagents/scripts/tradix-backup.sh /usr/local/bin/tradix-backup.sh
cat >/etc/cron.d/tradix-backup <<'EOF'
# Daily backup of Postgres + reports volume to gs://tradix-backups/
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
0 3 * * *  root  /usr/local/bin/tradix-backup.sh >> /var/log/tradix-backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/tradix-backup
touch /var/log/tradix-backup.log
chmod 0640 /var/log/tradix-backup.log

echo "==> Done."
echo ""
echo "Next:"
echo "  1. Place the env file at /etc/tradingagents/env (chmod 600)."
echo "  2. cd /srv/tradingagents && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

- [ ] **Step 2: Make it executable + lint**

```bash
chmod +x infra/bootstrap.sh
bash -n infra/bootstrap.sh
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add infra/bootstrap.sh
git commit -m "chore(deploy): add infra/bootstrap.sh (VM-side one-time setup)"
```

---

### Task 8: Add the backup script

**Files:**
- Create: `scripts/tradix-backup.sh`

- [ ] **Step 1: Write `scripts/tradix-backup.sh`**

```bash
#!/usr/bin/env bash
# Daily backup of TradingAgents prod state to gs://tradix-backups/.
# Installed at /usr/local/bin/tradix-backup.sh by infra/bootstrap.sh.
# Triggered by /etc/cron.d/tradix-backup at 03:00 Asia/Jakarta.
#
# Retention is enforced by a GCS object lifecycle rule (14 days) — this
# script never deletes anything.

set -euo pipefail

BUCKET="${BUCKET:-tradix-backups}"
TS="$(date +%Y%m%d-%H%M%S)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

DB_CONTAINER="$(docker ps -qf name=db | head -n1)"
if [[ -z "$DB_CONTAINER" ]]; then
  echo "FATAL: no running db container found" >&2
  exit 1
fi

echo "[$(date -Is)] backup start (ts=$TS)"

echo "[$(date -Is)] dumping Postgres"
docker exec -t "$DB_CONTAINER" \
  pg_dump -U trading trading_dashboard | gzip > "$TMPDIR/db-${TS}.sql.gz"

echo "[$(date -Is)] tarring dashdata volume"
docker run --rm \
  -v tradingagents_dashdata:/data:ro \
  -v "$TMPDIR":/backup \
  alpine tar -czf "/backup/reports-${TS}.tgz" -C /data .

echo "[$(date -Is)] uploading to gs://${BUCKET}/"
gcloud storage cp "$TMPDIR/db-${TS}.sql.gz"   "gs://${BUCKET}/db/"
gcloud storage cp "$TMPDIR/reports-${TS}.tgz" "gs://${BUCKET}/reports/"

echo "[$(date -Is)] backup done"
```

- [ ] **Step 2: Make it executable + lint**

```bash
chmod +x scripts/tradix-backup.sh
bash -n scripts/tradix-backup.sh
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add scripts/tradix-backup.sh
git commit -m "chore(deploy): add scripts/tradix-backup.sh (daily GCS backup)"
```

---

### Task 9: Add the GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write `.github/workflows/deploy.yml`**

```yaml
# Build + push api and web images to ghcr.io, then SSH to the prod VM and
# bounce the stack against the new images. Triggered on pushes to main.
#
# Required GitHub Secrets:
#   DEPLOY_HOST       — public hostname of the VM (tradix.axiara.ai)
#   DEPLOY_USER       — Linux user on the VM (typically erikgunawans or root)
#   DEPLOY_SSH_KEY    — private half of an ed25519 deploy key; public half is
#                       in ~DEPLOY_USER/.ssh/authorized_keys on the VM.

name: Deploy to tradix.axiara.ai

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-prod
  cancel-in-progress: false

permissions:
  contents: read
  packages: write

env:
  REGISTRY: ghcr.io
  IMAGE_PREFIX: ghcr.io/${{ github.repository_owner }}/tradingagents

jobs:
  build:
    name: Build ${{ matrix.service }} image
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - service: api
            context: .
            dockerfile: server/Dockerfile
          - service: web
            context: ./web
            dockerfile: ./web/Dockerfile
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.repository_owner }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/build-push-action@v6
        with:
          context: ${{ matrix.context }}
          file: ${{ matrix.dockerfile }}
          platforms: linux/amd64
          push: true
          tags: |
            ${{ env.IMAGE_PREFIX }}-${{ matrix.service }}:${{ github.sha }}
            ${{ env.IMAGE_PREFIX }}-${{ matrix.service }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    name: Deploy to VM
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Configure SSH
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.DEPLOY_SSH_KEY }}" > ~/.ssh/id_ed25519
          chmod 600 ~/.ssh/id_ed25519
          ssh-keyscan -H "${{ secrets.DEPLOY_HOST }}" >> ~/.ssh/known_hosts

      - name: Pull + restart on VM
        run: |
          ssh "${{ secrets.DEPLOY_USER }}@${{ secrets.DEPLOY_HOST }}" bash -lc '
            set -euo pipefail
            cd /srv/tradingagents
            git fetch --all
            git reset --hard origin/main
            export IMAGE_TAG=${{ github.sha }}
            echo "$IMAGE_TAG" > .current_image_tag
            docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
            docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
            docker image prune -f
          '

      - name: Smoke test
        run: |
          for i in {1..10}; do
            if curl -fsS "https://${{ secrets.DEPLOY_HOST }}/api/auth/providers" >/dev/null; then
              echo "Smoke test passed"
              exit 0
            fi
            sleep 5
          done
          echo "Smoke test FAILED after 50s" >&2
          exit 1
```

- [ ] **Step 2: Lint with actionlint (via docker, no install needed)**

```bash
docker run --rm -v "$PWD:/repo" rhysd/actionlint:latest \
  -color .github/workflows/deploy.yml
```

Expected: no output (no lint errors). If `actionlint` flags issues, fix them inline.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci(deploy): add deploy.yml — build + push to ghcr.io, SSH deploy to VM"
```

---

### Task 10: Add runbooks + deployment doc + README pointer

**Files:**
- Create: `docs/runbooks/first-boot.md`
- Create: `docs/runbooks/rollback.md`
- Create: `docs/runbooks/restore-from-backup.md`
- Create: `docs/deployment.md`
- Modify: `README.md` (one-line pointer)

- [ ] **Step 1: Create `docs/runbooks/` directory**

```bash
mkdir -p docs/runbooks
```

- [ ] **Step 2: Write `docs/runbooks/first-boot.md`**

````markdown
# First-boot runbook

This is what to do **once** when bringing up `tradix.axiara.ai` for the very first time.

## Prerequisites

- `infra/provision.sh` has been run and printed a static IP.
- Hostinger DNS A record for `tradix.axiara.ai` points at that IP.
- The GitHub OAuth app has `https://tradix.axiara.ai/api/auth/callback/github` in its callback whitelist.

## Steps

1. **Generate the env file locally**

   ```bash
   ./scripts/gen-prod-env.sh > /tmp/tradix.env
   ```

   Edit `/tmp/tradix.env` and fill in:
   - `AUTH_GITHUB_ID` + `AUTH_GITHUB_SECRET` from the OAuth app
   - `OPENROUTER_API_KEY` from your OpenRouter dashboard
   - (Optional) other `*_API_KEY` values

2. **Upload to the VM**

   ```bash
   gcloud compute scp /tmp/tradix.env $VM_NAME:/tmp/tradix.env --zone $GCP_ZONE
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- sudo install -m 0600 -o root -g root /tmp/tradix.env /etc/tradingagents/env
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- rm /tmp/tradix.env
   shred -u /tmp/tradix.env   # local copy
   ```

3. **First bring-up**

   ```bash
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- bash -lc '
     cd /srv/tradingagents
     export IMAGE_TAG=latest
     docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
     docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   '
   ```

4. **Wait for Caddy to fetch a Let's Encrypt cert** (~30 seconds on first run, may need up to 2 minutes if DNS hasn't propagated)

   ```bash
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- docker compose -f /srv/tradingagents/docker-compose.yml -f /srv/tradingagents/docker-compose.prod.yml logs caddy | tail -20
   ```

   Look for: `certificate obtained successfully` or `serving HTTPS on :443`.

5. **Verify from your laptop**

   ```bash
   curl -fsS -o /dev/null -w "%{http_code}\n" https://tradix.axiara.ai
   # Expected: 200 or 307 (NextAuth redirect to sign-in)
   ```

## The POSTGRES_PASSWORD gotcha

The Postgres image only honors `POSTGRES_PASSWORD` **on first init** (empty data directory). If you ever:

- Wipe `/etc/tradingagents/env` and re-generate with `scripts/gen-prod-env.sh` after the DB has data, OR
- Mis-type the password and need to change it

then the running DB still has the **old** password and `api`/`worker` will fail to connect.

Fix: either drop the volume (loses data) or `ALTER USER` inside the container:

```bash
# Inside the VM
docker exec -it $(docker ps -qf name=db) psql -U trading trading_dashboard -c \
  "ALTER USER trading WITH PASSWORD '<new password from env file>';"
```

Then restart api + worker so they pick up the new env value:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api worker
```
````

- [ ] **Step 3: Write `docs/runbooks/rollback.md`**

```markdown
# Rollback runbook

Every deploy tags both images with `:latest` and with the deploy's commit SHA.
To roll back, point the prod compose at a prior SHA.

## Steps

1. **Find the prior SHA**

   ```bash
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- cat /srv/tradingagents/.current_image_tag
   # Then look one commit back in github.com/erikgunawans/TradingAgents/commits/main
   ```

2. **Apply on the VM**

   ```bash
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- bash -lc '
     PREV_SHA=<paste-prior-sha-here>
     cd /srv/tradingagents
     export IMAGE_TAG=$PREV_SHA
     docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
     docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
     echo $PREV_SHA > .current_image_tag
   '
   ```

3. **Verify**

   ```bash
   curl -fsS -o /dev/null -w "%{http_code}\n" https://tradix.axiara.ai
   ```

   Expected: 200 or 307.

The repo on the VM is intentionally NOT rolled back via `git checkout` — only the
compose `image:` tag changes. Caddyfile + compose overlay stay on `main`.
```

- [ ] **Step 4: Write `docs/runbooks/restore-from-backup.md`**

````markdown
# Restore-from-backup runbook

Backups land in `gs://tradix-backups/db/` and `gs://tradix-backups/reports/`
nightly at 03:00 Asia/Jakarta. Retention is 14 days via GCS lifecycle.

## List available backups

```bash
gcloud storage ls gs://tradix-backups/db/   | sort -r | head -14
gcloud storage ls gs://tradix-backups/reports/ | sort -r | head -14
```

## Restore Postgres (destructive — overwrites prod DB)

```bash
DUMP=db-YYYYMMDD-HHMMSS.sql.gz   # pick from the list above

gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- bash -lc "
  cd /tmp && gcloud storage cp gs://tradix-backups/db/${DUMP} .
  docker exec -t \$(docker ps -qf name=db) psql -U trading -d postgres -c 'DROP DATABASE IF EXISTS trading_dashboard;'
  docker exec -t \$(docker ps -qf name=db) psql -U trading -d postgres -c 'CREATE DATABASE trading_dashboard;'
  gunzip -c ${DUMP} | docker exec -i \$(docker ps -qf name=db) psql -U trading trading_dashboard
"
```

## Restore reports volume (destructive — overwrites all reports)

```bash
REPORTS=reports-YYYYMMDD-HHMMSS.tgz

gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- bash -lc "
  cd /tmp && gcloud storage cp gs://tradix-backups/reports/${REPORTS} .
  docker run --rm -v tradingagents_dashdata:/data -v /tmp:/backup alpine \
    sh -c 'rm -rf /data/* && tar -xzf /backup/${REPORTS} -C /data'
"
```

## Non-destructive: restore into a scratch DB (drill / verification)

```bash
DUMP=db-YYYYMMDD-HHMMSS.sql.gz

gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- bash -lc "
  cd /tmp && gcloud storage cp gs://tradix-backups/db/${DUMP} .
  docker exec -t \$(docker ps -qf name=db) createdb -U trading restore_drill
  gunzip -c ${DUMP} | docker exec -i \$(docker ps -qf name=db) psql -U trading restore_drill
  docker exec -t \$(docker ps -qf name=db) psql -U trading restore_drill -c 'SELECT count(*) FROM runs;'
  docker exec -t \$(docker ps -qf name=db) dropdb -U trading restore_drill
"
```

Expected: the `SELECT count(*)` line returns a non-zero count matching the backup's run history.
````

- [ ] **Step 5: Write `docs/deployment.md`**

```markdown
# Production deployment

`tradix.axiara.ai` runs on a single GCP Compute Engine VM in `asia-southeast2-a`.

See [the design doc](superpowers/plans/2026-05-19-gcp-deployment-design.md) for
architecture and [the implementation plan](superpowers/plans/2026-05-19-gcp-deployment-plan.md)
for the build-out sequence.

## Runbooks

- [First boot](runbooks/first-boot.md) — bringing up the VM for the very first time
- [Rollback](runbooks/rollback.md) — reverting to a prior image
- [Restore from backup](runbooks/restore-from-backup.md) — recovering DB or reports

## Deploy flow

`git push origin main` → GitHub Actions builds api + web images, pushes to ghcr.io,
SSHes to the VM, pulls the new images, restarts the stack. Total time ~3 minutes.

## Quick-reference commands

```bash
# SSH to VM
gcloud compute ssh tradix --zone asia-southeast2-a

# Check stack health from VM
docker compose -f /srv/tradingagents/docker-compose.yml -f /srv/tradingagents/docker-compose.prod.yml ps

# Tail logs
docker compose -f /srv/tradingagents/docker-compose.yml -f /srv/tradingagents/docker-compose.prod.yml logs -f --tail=200

# Manual backup right now
sudo /usr/local/bin/tradix-backup.sh
```
```

- [ ] **Step 6: Add a one-line pointer to `README.md`**

Open `README.md` and add (or insert near the top, just below the existing intro):

```markdown
## Production deployment

`tradix.axiara.ai` — see [`docs/deployment.md`](docs/deployment.md).
```

- [ ] **Step 7: Commit**

```bash
git add docs/runbooks/ docs/deployment.md README.md
git commit -m "docs(deploy): add deployment.md + runbooks (first-boot, rollback, restore)"
```

---

## Phase 2 — Cloud bootstrap

> From here on, each task touches real cloud resources. You can pause + resume between tasks; nothing is destructive until you say so.

### Task 11: Run `infra/provision.sh` against GCP

**Files:** none (cloud-only operation).

- [ ] **Step 1: Confirm env vars are set**

```bash
echo "$GCP_PROJECT_ID $GCP_ZONE $VM_NAME $STATIC_IP_NAME $BUCKET_NAME $SA_NAME"
```

Expected: all 6 values present, no blanks.

- [ ] **Step 2: Run the script**

```bash
./infra/provision.sh 2>&1 | tee /tmp/provision-$(date +%Y%m%d-%H%M%S).log
```

Expected last lines:

```
Static IP:        <ip>
VM:               tradix in asia-southeast2-a
Service account:  tradix-vm@<project>.iam.gserviceaccount.com
Backup bucket:    gs://tradix-backups
```

- [ ] **Step 3: Note the static IP**

```bash
gcloud compute addresses describe "$STATIC_IP_NAME" --region "$GCP_REGION" --format='value(address)'
```

Save the value — you'll paste it into Hostinger in the next task.

No commit (cloud state only).

---

### Task 12: Configure Hostinger DNS

**Files:** none (manual UI step).

- [ ] **Step 1: Log in to Hostinger → hPanel → Domains → `axiara.ai` → DNS Zone Editor**

- [ ] **Step 2: Add A record**

| Field | Value |
|---|---|
| Type | A |
| Name | `tradix` |
| Points to | `<static IP from Task 11>` |
| TTL | 300 |

- [ ] **Step 3: Verify DNS from your laptop**

```bash
# Wait up to 5 minutes for propagation, then:
dig +short tradix.axiara.ai
```

Expected: prints the static IP.

No commit.

---

### Task 13: Add the second callback URL to the GitHub OAuth app

**Files:** none (manual UI step).

- [ ] **Step 1: Go to GitHub Settings → Developer settings → OAuth Apps → (the app NextAuth uses)**

- [ ] **Step 2: Under "Authorization callback URL", add as a second line:**

```
https://tradix.axiara.ai/api/auth/callback/github
```

(Keep the existing `http://localhost:3001/api/auth/callback/github` for dev.)

- [ ] **Step 3: Save. Copy `Client ID` + generate (or copy) `Client Secret` — you'll paste both into the prod env file in Task 16.**

No commit.

---

### Task 14: SSH to the VM and run `bootstrap.sh`

**Files:** none (cloud-only).

- [ ] **Step 1: SSH in**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE"
```

Expected: shell prompt on the VM. Your gcloud-provisioned SSH key is auto-installed by GCE.

- [ ] **Step 2: Run the bootstrap script (on the VM)**

```bash
# On the VM:
sudo bash -c 'curl -fsSL https://raw.githubusercontent.com/erikgunawans/TradingAgents/main/infra/bootstrap.sh -o /tmp/bootstrap.sh && bash /tmp/bootstrap.sh'
```

Expected last line: `Done.` Total runtime ~3-4 minutes.

- [ ] **Step 3: Verify Docker installed**

```bash
# On the VM:
docker version
docker compose version
```

Expected: both show v2+.

- [ ] **Step 4: Verify the repo is in place**

```bash
# On the VM:
ls /srv/tradingagents/docker-compose.prod.yml /srv/tradingagents/Caddyfile
```

Expected: both files exist.

- [ ] **Step 5: Exit SSH**

```bash
# On the VM:
exit
```

No commit.

---

### Task 15: Place the prod env file on the VM

**Files:** none (cloud-only).

- [ ] **Step 1: Generate the env locally + fill in the manual values**

```bash
./scripts/gen-prod-env.sh > /tmp/tradix.env
```

Open `/tmp/tradix.env` in your editor and replace:
- `PASTE_FROM_GITHUB_OAUTH_APP` (Client ID) → from Task 13
- `PASTE_FROM_GITHUB_OAUTH_APP` (Client Secret) → from Task 13
- `PASTE_FROM_OPENROUTER_DASHBOARD` → your OpenRouter API key

- [ ] **Step 2: Copy to VM, install, scrub local copy**

```bash
gcloud compute scp /tmp/tradix.env "$VM_NAME":/tmp/tradix.env --zone "$GCP_ZONE"

gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- sudo install -m 0600 -o root -g root /tmp/tradix.env /etc/tradingagents/env

gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- rm /tmp/tradix.env

# Local copy
shred -u /tmp/tradix.env 2>/dev/null || rm /tmp/tradix.env
```

- [ ] **Step 3: Verify it's in place on the VM**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- sudo ls -la /etc/tradingagents/env
```

Expected: `-rw------- 1 root root <bytes>` (mode 600, root owner).

No commit.

---

### Task 16: First bring-up and verify HTTPS

**Files:** none (cloud-only).

- [ ] **Step 1: Bring the stack up on the VM**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- bash -lc '
  cd /srv/tradingagents
  git pull origin main
  export IMAGE_TAG=latest
  docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
'
```

> **Note:** `docker compose pull` will fail at this point because the `:latest` images don't exist in ghcr.io yet (CI hasn't run). That's OK — `docker compose up -d` will fall back to building locally from the Dockerfiles. The local build takes longer (~5 minutes on `e2-medium`) but works. Once Task 20 lands a successful CI deploy, future deploys use the prebuilt images instantly.

Expected: `Container tradingagents-caddy-1 Started` etc., 6 containers running.

- [ ] **Step 2: Tail Caddy logs and wait for cert**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- \
  docker compose -f /srv/tradingagents/docker-compose.yml -f /srv/tradingagents/docker-compose.prod.yml logs caddy | tail -30
```

Expected: a line containing `certificate obtained successfully` or `serving HTTPS on :443`.

- [ ] **Step 3: Verify HTTPS from your laptop**

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" https://tradix.axiara.ai
```

Expected: `200` or `307` (NextAuth redirect to sign-in).

- [ ] **Step 4: Verify the cert is real (not the Caddy self-signed fallback)**

```bash
echo | openssl s_client -connect tradix.axiara.ai:443 -servername tradix.axiara.ai 2>/dev/null | openssl x509 -noout -issuer -subject
```

Expected: issuer contains `Let's Encrypt`, subject contains `tradix.axiara.ai`.

No commit.

---

### Task 17: End-to-end OAuth + analysis run verification

**Files:** none (manual UI verification).

- [ ] **Step 1: Browse to `https://tradix.axiara.ai` in a normal browser**

Expected: sign-in page renders with no cert warnings.

- [ ] **Step 2: Click "Sign in with GitHub"**

Expected: redirects to GitHub, you authorize the app, you land back on the dashboard signed in.

- [ ] **Step 3: Launch a test analysis run**

Use ticker `BBCA.JK` (exercises the new IDX path from PR #17/#18).

Expected: the run shows up on `/history`, status progresses from `PENDING` → `RUNNING`, the live log stream shows worker activity, the worker log stream shows at least `[market_analyst] starting` (regardless of whether the LLM call succeeds; OpenRouter quota will determine that).

- [ ] **Step 4: If the run fails, sanity-check the LLM key**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- \
  docker compose -f /srv/tradingagents/docker-compose.yml -f /srv/tradingagents/docker-compose.prod.yml logs worker --tail 50
```

Look for either a `401` (bad/missing OpenRouter key) or a successful LLM API response.

No commit.

---

## Phase 3 — CI/CD

### Task 18: Generate and install the SSH deploy key

**Files:** none (cloud-only).

- [ ] **Step 1: Generate an ed25519 keypair locally (dedicated to CI — do not reuse personal key)**

```bash
ssh-keygen -t ed25519 -f /tmp/tradix-deploy -N "" -C "github-actions-deploy"
```

Expected: files `/tmp/tradix-deploy` (private) and `/tmp/tradix-deploy.pub` (public).

- [ ] **Step 2: Install the public key on the VM**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- bash -lc '
  mkdir -p ~/.ssh && chmod 700 ~/.ssh
  cat >> ~/.ssh/authorized_keys
' < /tmp/tradix-deploy.pub
```

- [ ] **Step 3: Test the key from your laptop directly (no gcloud wrapping)**

```bash
DEPLOY_USER=$(gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- whoami)
VM_IP=$(gcloud compute addresses describe "$STATIC_IP_NAME" --region "$GCP_REGION" --format='value(address)')

ssh -i /tmp/tradix-deploy -o StrictHostKeyChecking=accept-new "${DEPLOY_USER}@${VM_IP}" whoami
```

Expected: prints `$DEPLOY_USER`.

- [ ] **Step 4: Record values for the next task — DO NOT commit these**

```bash
echo "DEPLOY_USER=$DEPLOY_USER"
echo "DEPLOY_HOST=tradix.axiara.ai"
echo "DEPLOY_SSH_KEY="
cat /tmp/tradix-deploy
```

- [ ] **Step 5: Clean up the local private key after Task 19 succeeds (you don't need it once it's in GitHub Secrets)**

```bash
# After Task 19:
shred -u /tmp/tradix-deploy 2>/dev/null || rm /tmp/tradix-deploy
rm /tmp/tradix-deploy.pub
```

No commit.

---

### Task 19: Add GitHub Actions secrets

**Files:** none (manual UI step).

- [ ] **Step 1: Go to `github.com/erikgunawans/TradingAgents` → Settings → Secrets and variables → Actions → New repository secret**

- [ ] **Step 2: Add three secrets**

| Name | Value |
|---|---|
| `DEPLOY_HOST` | `tradix.axiara.ai` |
| `DEPLOY_USER` | (value of `whoami` from Task 18) |
| `DEPLOY_SSH_KEY` | the entire contents of `/tmp/tradix-deploy` including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----` lines |

- [ ] **Step 3: Verify Actions is enabled for the repo**

`Settings → Actions → General → Allow all actions and reusable workflows`.

No commit.

---

### Task 20: Trigger first end-to-end deploy

**Files:** none (verification only).

- [ ] **Step 1: Push the feature branch and open a PR**

```bash
git push fork feature/gcp-deploy
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(deploy): production deploy to tradix.axiara.ai via GCP + GitHub Actions" \
  --body "$(cat <<'EOF'
## Summary

Adds the production-deploy machinery to ship the TradingAgents stack to
`https://tradix.axiara.ai` on a single GCP Compute Engine VM.

- New `docker-compose.prod.yml` overlay + `Caddyfile` for the prod stack
- `infra/provision.sh` (GCP one-time setup) + `infra/bootstrap.sh` (VM-side setup)
- `scripts/tradix-backup.sh` + cron for daily Postgres + reports backups to GCS
- `.github/workflows/deploy.yml` for build → push → SSH deploy on push to main
- Runbooks: first-boot, rollback, restore-from-backup

Design: `docs/superpowers/plans/2026-05-19-gcp-deployment-design.md`
Plan: `docs/superpowers/plans/2026-05-19-gcp-deployment-plan.md`

## Test plan

- [ ] Phase 1 tasks 2-10 each verified locally (compose validates, scripts lint, actionlint clean)
- [ ] Phase 2 cloud bootstrap completes; `https://tradix.axiara.ai` returns 200/307 with a Let's Encrypt cert
- [ ] GitHub OAuth sign-in completes end-to-end
- [ ] BBCA.JK analysis run reaches `[market_analyst] starting` in the worker log
- [ ] First CI deploy succeeds; smoke test in the workflow returns 200
- [ ] Daily backup lands in `gs://tradix-backups/` within 24h
- [ ] Restore drill into scratch DB succeeds

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Watch the Actions tab**

```bash
gh run watch --repo erikgunawans/TradingAgents
```

Expected: both `build` matrix jobs (api + web) finish in <3 min; `deploy` job finishes in <30 sec; `smoke test` step returns 200.

- [ ] **Step 3: Verify the deploy actually swapped the image tag**

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- cat /srv/tradingagents/.current_image_tag
```

Expected: the commit SHA of the PR's HEAD (not `latest`).

- [ ] **Step 4: Make a no-op edit on `main` after merging and confirm the deploy triggers**

After PR merges:

```bash
# Local
git checkout main && git pull fork main
echo "" >> docs/deployment.md   # trivial change
git commit -am "chore: trigger CI deploy" && git push fork main
gh run watch --repo erikgunawans/TradingAgents
```

Expected: deploy completes, `.current_image_tag` updates to the new SHA.

No commit (the no-op already commits).

---

## Phase 4 — Backup verification

### Task 21: Verify the first scheduled backup lands

**Files:** none (verification only).

- [ ] **Step 1: Wait for the 03:00 Asia/Jakarta cron run** (or manually trigger to skip the wait)

To trigger manually:

```bash
gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- sudo /usr/local/bin/tradix-backup.sh
```

Expected: prints `backup done` on the last line within ~30 seconds.

- [ ] **Step 2: List the bucket**

```bash
gcloud storage ls gs://tradix-backups/db/
gcloud storage ls gs://tradix-backups/reports/
```

Expected: each lists at least one object with today's date in the filename.

- [ ] **Step 3: Confirm the lifecycle rule is in place**

```bash
gcloud storage buckets describe gs://tradix-backups --format='value(lifecycle)'
```

Expected: shows a Delete-after-14-days rule.

No commit.

---

### Task 22: Restore drill into a scratch DB

**Files:** none (verification only).

- [ ] **Step 1: Follow the non-destructive recipe in `docs/runbooks/restore-from-backup.md`**

```bash
DUMP=$(gcloud storage ls gs://tradix-backups/db/ | tail -1 | xargs basename)

gcloud compute ssh "$VM_NAME" --zone "$GCP_ZONE" -- bash -lc "
  cd /tmp && gcloud storage cp gs://tradix-backups/db/${DUMP} .
  docker exec -t \$(docker ps -qf name=db) createdb -U trading restore_drill
  gunzip -c ${DUMP} | docker exec -i \$(docker ps -qf name=db) psql -U trading restore_drill
  docker exec -t \$(docker ps -qf name=db) psql -U trading restore_drill -c 'SELECT count(*) FROM runs;'
  docker exec -t \$(docker ps -qf name=db) dropdb -U trading restore_drill
  rm /tmp/${DUMP}
"
```

Expected: the `SELECT count(*)` line returns the same number of runs as `https://tradix.axiara.ai/history` shows.

No commit (drill only).

---

## Phase 5 — Ship

### Task 23: Update PROGRESS.md + close the loop

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Branch from main + add a checkpoint section to `PROGRESS.md`**

```bash
git checkout main && git pull fork main
git checkout -b chore/progress-md-gcp-deploy
```

Append a new checkpoint to `PROGRESS.md` immediately after the existing 2026-05-19 (PR #17 + #18) section:

```markdown
---

## Checkpoint 2026-05-19 (continued — PR #19 merged, GCP deploy live)

- **What landed:** Production deploy to `https://tradix.axiara.ai` on a single
  GCP Compute Engine VM (`e2-medium`, `asia-southeast2-a`). Single portable
  `docker-compose` artifact; Caddy terminates TLS; GitHub Actions builds + pushes
  api + web images to `ghcr.io/erikgunawans/tradingagents-{api,web}`; daily 03:00
  Asia/Jakarta cron backs Postgres + reports up to `gs://tradix-backups/` with a
  14-day lifecycle.
- **Cost:** ~$25/mo VM + ~$0.10/mo backups.
- **What's reachable publicly:** ports 22 (SSH, key-only + fail2ban), 80 (HTTP→HTTPS
  redirect + ACME challenge), 443 (HTTPS). Nothing else.
- **Followups carried forward:**
  - Move backups under a less-blast-radius service account if multi-tenant ever ships.
  - Add Cloudflare in front when public traffic justifies it (free tier; ~10 min to switch).
  - Add structured log aggregation (currently `docker compose logs` on the VM only).
  - Worker `_persist_reports` unification — still open from PR #14 era.

| Metric | Value |
|---|---|
| Local main HEAD | `<final-sha>` |
| Most recent PR | #19 — production deploy to tradix.axiara.ai |
| Public surface | `https://tradix.axiara.ai` |
| VM | e2-medium / asia-southeast2-a |
| Backup bucket | gs://tradix-backups/ |
```

Replace `<final-sha>` with `git log -1 --format=%h` once the PR merges.

- [ ] **Step 2: Update the top-of-file Current State block**

In the table, replace `Most recent PR | #18` with `Most recent PR | #19 — production deploy to tradix.axiara.ai`.

In the "What To Do Next" section, replace the active 🚀 deployment item with:

```markdown
- **✅ Cloud + VPS deployment (shipped)** — `tradix.axiara.ai` is live on GCP. See `docs/deployment.md` + the design + plan docs under `docs/superpowers/plans/`. The same docker-compose stack remains VPS-portable if you ever switch.
```

- [ ] **Step 3: Commit + PR + merge**

```bash
git add PROGRESS.md
git commit -m "docs: PROGRESS.md checkpoint for tradix.axiara.ai production deploy"
git push fork chore/progress-md-gcp-deploy
gh pr create --repo erikgunawans/TradingAgents \
  --title "docs: PROGRESS.md checkpoint for tradix.axiara.ai production deploy" \
  --body "Follow-up to PR #19. Refreshes Current State + What To Do Next + adds the GCP-deploy checkpoint section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

After merge:

```bash
git checkout main && git pull fork main
```

---

## Acceptance criteria

Mapping back to design §12:

- [ ] **§12.1** `https://tradix.axiara.ai` returns the dashboard with a valid Let's Encrypt cert → verified in Task 16 + Task 17.
- [ ] **§12.2** GitHub OAuth sign-in completes end-to-end → Task 17.
- [ ] **§12.3** Test analysis run (e.g., `BBCA.JK`) reaches at least the LLM API call stage → Task 17.
- [ ] **§12.4** `git push origin main` ships to prod in <5 minutes with no manual steps → Task 20.
- [ ] **§12.5** `gs://tradix-backups/db/` contains at least one `pg_dump` artifact + reports tarball within 24h → Task 21.
- [ ] **§12.6** Restore-into-scratch-DB drill from a backup artifact succeeds → Task 22.
- [ ] **§12.7** No public ports exposed beyond 22 / 80 / 443 → Task 5 (compose merge) + Task 11 (firewall rules).
- [ ] **§12.8** Same `docker-compose.yml` (without `docker-compose.prod.yml`) still works locally for dev — `docker compose up` on the dev compose alone still works unchanged.

When all 8 criteria check, the deploy is "done".
