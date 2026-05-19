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
