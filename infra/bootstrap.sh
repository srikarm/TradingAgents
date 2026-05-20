#!/usr/bin/env bash
# Runs ON the VM (not on your laptop). Installs Docker, fail2ban, clones the
# repo to /srv/tradingagents, installs the backup script and cron entry, and
# sets perms so the GitHub Actions deploy user can drive `git pull` + docker
# compose without sudo.
#
# Idempotent: re-running should be a no-op once the VM is set up.

set -euo pipefail

FORK_REPO="${FORK_REPO:-erikgunawans/TradingAgents}"
# The CI deploy SSHes in as this user. Defaults to the user who ran `sudo
# bash bootstrap.sh` (SUDO_USER), which on a GCE Debian image is the gcloud
# OS Login identity. Override by exporting DEPLOY_USER before running.
DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-}}"

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
# Hand the repo to the CI deploy user so `git fetch && git reset --hard`
# in the GitHub Actions workflow works without sudo. If DEPLOY_USER isn't
# set or doesn't exist, fall back to root:root (the deploy will then need
# to use sudo, but the bootstrap still completes).
if [[ -n "$DEPLOY_USER" ]] && id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "    Owner: $DEPLOY_USER (CI deploy identity)"
  chown -R "$DEPLOY_USER:$DEPLOY_USER" /srv/tradingagents
else
  echo "    Owner: root:root (DEPLOY_USER not set or unknown — CI deploy will need sudo)"
  chown -R root:root /srv/tradingagents
fi
# Tell git this directory is safe even if its owner doesn't match the
# user invoking git (CVE-2022-24765 guard). Belt-and-suspenders for the
# case where DEPLOY_USER is set later than bootstrap.
git config --system --add safe.directory /srv/tradingagents

echo "==> Creating /etc/tradingagents/"
mkdir -p /etc/tradingagents
# Root owns + writes; docker-group members can traverse + read the env file.
# This is the minimum perm set so that `docker compose --env-file ...` from
# the CI deploy works without sudo. The docker group already grants effective
# root via the docker socket, so widening read access to that group doesn't
# materially expand the trust boundary.
chown root:docker /etc/tradingagents
chmod 750 /etc/tradingagents

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
echo "  2. cd /srv/tradingagents && docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml up -d"
