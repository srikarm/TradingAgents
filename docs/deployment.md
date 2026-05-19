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
