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
echo "  2. cd /srv/tradingagents && docker compose --env-file /etc/tradingagents/env -f docker-compose.yml -f docker-compose.prod.yml up -d"
