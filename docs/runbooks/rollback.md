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
     docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml pull
     docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml up -d
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
