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

LIFECYCLE_FILE="$(mktemp)"
trap 'rm -f "$LIFECYCLE_FILE"' EXIT

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
cat >"$LIFECYCLE_FILE" <<'JSON'
{
  "rule": [
    { "action": {"type": "Delete"}, "condition": {"age": 14} }
  ]
}
JSON
gcloud storage buckets update "gs://$BUCKET_NAME" --lifecycle-file="$LIFECYCLE_FILE"

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
