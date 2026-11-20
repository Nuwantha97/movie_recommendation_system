#!/usr/bin/env bash
# Run manually on Amazon Linux 2023 AFTER EC2 and RDS are created.
# Downloads Compose from Docker's official GitHub release when AL2023 lacks plugin.
set -Eeuo pipefail
[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
REPO=/opt/movie-recs/movie_recommendation_system
[[ -f "${REPO}/compose.ec2.yml" ]] || { echo "Clone the repository to ${REPO} first" >&2; exit 1; }

dnf install -y docker git python3 python3-pip curl gzip util-linux
systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  # Official static CLI plugin; pin the release for repeatability.
  COMPOSE_VERSION=v5.6.0
  install -d -m 755 /usr/local/lib/docker/cli-plugins
  case "$(uname -m)" in
    x86_64)  ARCH=x86_64 ;;
    aarch64) ARCH=aarch64 ;;
    *) echo "Unsupported Compose CPU architecture" >&2; exit 1 ;;
  esac
  curl --fail --location --show-error --silent \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose
fi
docker compose version

install -d -m 755 /opt/movie-recs
install -d -m 700 /etc/movie-recs /var/lib/movie-recs
if [[ ! -x /opt/movie-recs/venv/bin/python ]]; then
  python3 -m venv /opt/movie-recs/venv
fi
/opt/movie-recs/venv/bin/python -m pip install --upgrade pip
/opt/movie-recs/venv/bin/python -m pip install 'dvc[http]' 'psycopg[binary]' 'python-dotenv'

curl --fail --location --show-error --silent \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  -o /etc/movie-recs/global-bundle.pem
chmod 644 /etc/movie-recs/global-bundle.pem

if [[ ! -f /etc/movie-recs/deploy.env ]]; then
  install -m 600 "${REPO}/deploy/aws/deploy.env.example" /etc/movie-recs/deploy.env
  echo "Created /etc/movie-recs/deploy.env: edit placeholders before deploying."
fi
chown root:root /etc/movie-recs/deploy.env
chmod 600 /etc/movie-recs/deploy.env
chmod 755 "${REPO}/deploy/aws/entrypoint.sh"
echo "Bootstrap ready. Configure /etc/movie-recs/deploy.env; do not store secrets in Git."
