# First-boot runbook

This is what to do **once** when bringing up `tradix.axiara.ai` for the very first time.

## Prerequisites

- `infra/provision.sh` has been run and printed a static IP.
- DNS A record for `tradix.axiara.ai` points at that IP. **Where DNS lives can differ from where the domain is registered** — `axiara.ai` is registered at Hostinger but its nameservers may be delegated to Cloudflare (`*.ns.cloudflare.com`). Check via Hostinger's `DNS / Nameservers` panel: if it says "Your domain's DNS records are currently managed elsewhere," add the record at the provider whose nameservers are active (most likely Cloudflare → `dash.cloudflare.com` → DNS → Records). For the no-Cloudflare-proxy design, set the proxy status to "DNS only" (gray cloud, not orange).
- The GitHub OAuth app has `https://tradix.axiara.ai/api/auth/callback/github` in its callback whitelist. **If you haven't created one yet** — dev mode uses an `E2E_TEST_MODE` bypass that doesn't need a real OAuth app, so production needs a fresh one. Register at https://github.com/settings/developers → OAuth Apps → New OAuth app. Homepage: `https://tradix.axiara.ai`, Authorization callback URL: `https://tradix.axiara.ai/api/auth/callback/github`. Copy the Client ID + generated Client Secret to a password manager.
- The Google OAuth client has `https://tradix.axiara.ai/api/auth/callback/google` in its authorized redirect URIs. Create one at https://console.cloud.google.com/apis/credentials → Create Credentials → OAuth client ID → Application type: Web application. Authorized redirect URIs: `https://tradix.axiara.ai/api/auth/callback/google` (and optionally `http://localhost:3001/api/auth/callback/google` for dev). Copy the Client ID + Client Secret. **Consent screen:** keep the OAuth consent screen in "Testing" mode and add your own email + any allowed signers under "Test users". Requesting Google's app verification is a multi-day process and only needed once unverified-app usage exceeds Google's quotas. Expand the test-users list as new people need access.
- If `DEPLOY_USER` (the user the GitHub Actions deploy job SSHes in as) is non-root, that user must be in the `docker` group on the VM. `bootstrap.sh` chowns `/srv/tradingagents` to `$SUDO_USER` (i.e. the user who ran `sudo bash bootstrap.sh`) and group-grants `docker` on `/etc/tradingagents/`, so the gcloud-default `gcloud compute ssh` user works out of the box. If you set a different `DEPLOY_USER`, export it before running `bootstrap.sh`, and ensure it's in the `docker` group.
- (Optional) Confirm the LLM model IDs you'll use are actually available — OpenRouter regularly retires older model variants. Query `https://openrouter.ai/api/v1/models` and look for the IDs you've set in `DEFAULT_DEEP_THINK_LLM` / `DEFAULT_QUICK_THINK_LLM`. Note: current Anthropic IDs use DOT separators (`claude-sonnet-4.6`), not dashes.

## Steps

1. **Generate the env file locally**

   ```bash
   ./scripts/gen-prod-env.sh > /tmp/tradix.env
   ```

   Edit `/tmp/tradix.env` and fill in:
   - `AUTH_GITHUB_ID` + `AUTH_GITHUB_SECRET` from the GitHub OAuth app
   - `AUTH_GOOGLE_ID` + `AUTH_GOOGLE_SECRET` from the Google OAuth client
   - `OPENROUTER_API_KEY` from your OpenRouter dashboard
   - (Optional) other `*_API_KEY` values

2. **Upload to the VM**

   ```bash
   gcloud compute scp /tmp/tradix.env $VM_NAME:/tmp/tradix.env --zone $GCP_ZONE
   # mode 640 + group=docker so the CI deploy user (in docker group) can read
   # the env file without sudo. bootstrap.sh sets /etc/tradingagents/ to
   # mode 750 root:docker for the same reason.
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- sudo install -m 0640 -o root -g docker /tmp/tradix.env /etc/tradingagents/env
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- rm /tmp/tradix.env
   shred -u /tmp/tradix.env   # local copy
   ```

3. **First bring-up**

   ```bash
   gcloud compute ssh $VM_NAME --zone $GCP_ZONE -- bash -lc '
     cd /srv/tradingagents
     export IMAGE_TAG=latest
     docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml pull
     docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml up -d
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
