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
