#!/usr/bin/env bash
# This runs as root via AWS-RunShellScript or sudo. Serialises all deployments.
set -Eeuo pipefail
TARGET_SHA="${1:?Pass a full Git commit SHA}"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA'; exit 2; }
REPO=/opt/movie-recs/movie_recommendation_system
# DVC is installed in the dedicated deploy venv, not on system PATH.
export PATH="/opt/movie-recs/venv/bin:$PATH"
exec 9>/var/lock/movie-recs-deploy.lock
flock -n 9 || { echo 'Another deployment is already running'; exit 1; }
cd "$REPO"
OLD_SHA="$(git rev-parse HEAD)"
git fetch --no-tags origin main
git cat-file -e "${TARGET_SHA}^{commit}"
git merge-base --is-ancestor "$TARGET_SHA" origin/main || { echo 'SHA is not on origin/main'; exit 1; }
git checkout --force --detach "$TARGET_SHA"
if PREVIOUS_SOURCE_SHA="$OLD_SHA" /opt/movie-recs/venv/bin/python deploy/aws/sync.py; then
  echo "DEPLOYMENT_OK: $TARGET_SHA"
else
  rc=$?
  echo "Deployment failed; restoring source checkout $OLD_SHA" >&2
  git checkout --force --detach "$OLD_SHA" || true
  # sync.py handles DB/backend image rollback; restore previous frontend as well.
  if [ -f frontend/package-lock.json ]; then
    docker run --rm -v "$REPO/frontend:/work" -w /work node:22-alpine sh -ec 'npm ci && npm run build' || true
  fi
  exit "$rc"
fi
