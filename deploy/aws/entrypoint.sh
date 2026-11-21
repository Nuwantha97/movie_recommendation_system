#!/usr/bin/env bash
# Executed by dispatch.sh in the extracted release with the host lock held.
set -euo pipefail
umask 077
export RELEASE_SHA="$1" AWS_DEFAULT_REGION="$2" RDS_HOST="$3" RDS_PORT="$4"
export MASTER_SECRET_ARN="$5" RUNTIME_SECRET_NAME="$6" SITE_ADDRESS="$7" CORS_ORIGINS="$8"
export AWS_PAGER=""
install -d -m 700 /opt/movie-recs /etc/movie-recs /var/lib/movie-recs
if ! command -v python3.11 >/dev/null || ! command -v docker >/dev/null || ! command -v git >/dev/null; then
  dnf install -y docker git python3.11 python3.11-pip
fi
systemctl enable --now docker
if ! docker compose version >/dev/null 2>&1; then
  plugin=/usr/local/lib/docker/cli-plugins/docker-compose
  install -d -m 755 "$(dirname "$plugin")"
  curl --fail --location --retry 3 --silent --show-error \
    "https://github.com/docker/compose/releases/download/v2.39.4/docker-compose-linux-$(uname -m)" -o "$plugin.tmp"
  chmod 755 "$plugin.tmp"
  mv "$plugin.tmp" "$plugin"
fi
venv=/opt/movie-recs/deploy-venv
if [[ ! -f "$venv/.ready-v1" ]]; then
  python3.11 -m venv "$venv"
  "$venv/bin/pip" install 'dvc>=3,<4' dvc-http 'psycopg[binary]>=3,<4'
  touch "$venv/.ready-v1"
fi
export PATH="$venv/bin:$PATH"
ca=/etc/movie-recs/global-bundle.pem
curl --fail --location --retry 3 --silent --show-error \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o "$ca.tmp"
chmod 644 "$ca.tmp"
mv "$ca.tmp" "$ca"
# Git metadata lets DVC discover the archived project, even for a private repository.
git init -q
exec python deploy/aws/sync.py
