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
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

DB_CONTAINER="$(docker ps -qf name=db | head -n1)"
if [[ -z "$DB_CONTAINER" ]]; then
  echo "FATAL: no running db container found" >&2
  exit 1
fi

echo "[$(date -Is)] backup start (ts=$TS)"

echo "[$(date -Is)] dumping Postgres"
docker exec -t "$DB_CONTAINER" \
  pg_dump -U trading trading_dashboard | gzip > "$WORK_DIR/db-${TS}.sql.gz"

echo "[$(date -Is)] tarring dashdata volume"
docker run --rm \
  -v tradingagents_dashdata:/data:ro \
  -v "$WORK_DIR":/backup \
  alpine tar -czf "/backup/reports-${TS}.tgz" -C /data .

echo "[$(date -Is)] uploading to gs://${BUCKET}/"
gcloud storage cp "$WORK_DIR/db-${TS}.sql.gz"   "gs://${BUCKET}/db/"
gcloud storage cp "$WORK_DIR/reports-${TS}.tgz" "gs://${BUCKET}/reports/"

echo "[$(date -Is)] backup done"
