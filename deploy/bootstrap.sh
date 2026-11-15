#!/usr/bin/env bash
# ==============================================================================
# DualLens Movie Recommendation System - Azure / Production Bootstrap Script
# ==============================================================================
# Automates:
#  1. DVC pull of artifacts (~3.1 GB) & database dump (~319 MB) from DagsHub
#  2. Safe, idempotent PostgreSQL restoration (skips if tables already exist)
#  3. Frontend asset compilation
#  4. Launching production containers (PostgreSQL, FastAPI Backend, Caddy Proxy)
# ==============================================================================

set -euo pipefail

# Resolve project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================================="
echo " Starting DualLens Production Bootstrap on $(hostname)"
echo " Repository root: $REPO_ROOT"
echo "=========================================================="

# ------------------------------------------------------------------------------
# 1. Load Environment Variables
# ------------------------------------------------------------------------------
if [ -f ".env" ]; then
    echo "Loading environment variables from .env ..."
    # Export non-comment lines
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
else
    echo "ERROR: .env file not found in $REPO_ROOT."
    echo "Please copy .env.example to .env and configure credentials before running."
    exit 1
fi

: "${POSTGRES_USER:?POSTGRES_USER must be set in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB must be set in .env}"

# ------------------------------------------------------------------------------
# 2. Check & Configure DVC for DagsHub
# ------------------------------------------------------------------------------
echo ""
echo "=== Step 1: Checking DVC & DagsHub Storage ==="

if ! command -v dvc &>/dev/null; then
    echo "DVC not found in PATH. Checking python venv or pip..."
    if [ -f "backend/.venv/bin/dvc" ]; then
        export PATH="$REPO_ROOT/backend/.venv/bin:$PATH"
    elif python3 -m dvc --version &>/dev/null; then
        dvc() { python3 -m dvc "$@"; }
    else
        echo "Installing DVC with pip..."
        pip install --quiet dvc
    fi
fi

# Configure DagsHub credentials if provided in .env
if [ -n "${DAGSHUB_USER:-}" ] && [ -n "${DAGSHUB_TOKEN:-}" ]; then
    echo "Configuring local DVC credentials for DagsHub..."
    dvc remote modify origin --local auth basic
    dvc remote modify origin --local user "$DAGSHUB_USER"
    dvc remote modify origin --local password "$DAGSHUB_TOKEN"
fi

# ------------------------------------------------------------------------------
# 3. Pull ML Artifacts & DB Dump (Idempotent)
# ------------------------------------------------------------------------------
echo ""
echo "=== Step 2: Verifying & Pulling Data Assets via DVC ==="

ARTIFACTS_KEY_FILE="./backend/artifacts/v1/plot_embeddings.npy"
DB_DUMP_FILE="./database/moviedb.sql.gz"
NEED_PULL=0

if [ ! -f "$ARTIFACTS_KEY_FILE" ]; then
    echo "-> Artifacts missing (cannot find $ARTIFACTS_KEY_FILE)."
    NEED_PULL=1
else
    echo "-> Artifacts already present on disk at backend/artifacts/v1/."
fi

if [ ! -f "$DB_DUMP_FILE" ]; then
    echo "-> Database dump missing (cannot find $DB_DUMP_FILE)."
    NEED_PULL=1
else
    echo "-> Database dump already present at $DB_DUMP_FILE."
fi

if [ "$NEED_PULL" -eq 1 ]; then
    echo "-> Pulling required assets from DagsHub (this may take 2-4 minutes on first run)..."
    dvc pull backend/artifacts/v1.dvc database/moviedb.sql.gz.dvc
    echo "-> DVC pull completed successfully."
else
    echo "-> All large assets already exist. Skipping DVC download."
fi

# Verify artifacts exist before moving on
if [ ! -f "$ARTIFACTS_KEY_FILE" ]; then
    echo "ERROR: Artifacts still missing after DVC pull. Check DagsHub credentials and connection."
    exit 1
fi

# ------------------------------------------------------------------------------
# 4. Start PostgreSQL Database & Wait for Health
# ------------------------------------------------------------------------------
echo ""
echo "=== Step 3: Starting PostgreSQL Service ==="
docker compose up -d database

echo "Waiting for PostgreSQL engine to be ready..."
RETRIES=30
until docker compose exec -T database pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" &>/dev/null || [ "$RETRIES" -eq 0 ]; do
    echo -n "."
    sleep 2
    RETRIES=$((RETRIES - 1))
done
echo ""

if [ "$RETRIES" -eq 0 ]; then
    echo "ERROR: PostgreSQL service failed to become ready in time."
    docker compose logs database
    exit 1
fi
echo "PostgreSQL is ready and accepting connections."

# ------------------------------------------------------------------------------
# 5. Restore Database from Dump (Idempotent)
# ------------------------------------------------------------------------------
echo ""
echo "=== Step 4: Checking Database Schema & Tables ==="

# Check if 'movies' table already exists in the database
TABLE_EXISTS=$(docker compose exec -T database psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'movies');" 2>/dev/null || echo "f")

if [ "$TABLE_EXISTS" != "t" ]; then
    echo "Database is empty! Restoring TMDB data from $DB_DUMP_FILE ..."
    echo "This uncompresses ~319 MB and indexes ~700,000+ movie rows (~1-2 mins)..."
    gunzip -c "$DB_DUMP_FILE" | docker compose exec -T database psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q
    
    # Configure read-only application role
    if [ -f "database/create_app_role.sql" ]; then
        echo "Creating restricted 'app_ro' database role..."
        docker compose exec -i database psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < database/create_app_role.sql
    fi
    echo "Database restoration and roles successfully configured."
else
    echo "PostgreSQL 'movies' table already exists in pgdata volume. Skipping database restore."
fi

# ------------------------------------------------------------------------------
# 6. Build Frontend Static Assets
# ------------------------------------------------------------------------------
echo ""
echo "=== Step 5: Building Frontend Production Assets ==="

if command -v npm &>/dev/null; then
    echo "Compiling frontend bundle with Vite..."
    cd frontend
    if [ ! -d "node_modules" ]; then
        echo "Installing frontend dependencies..."
        npm ci || npm install
    fi
    npm run build
    cd "$REPO_ROOT"
    echo "Frontend build ready at frontend/dist/."
else
    if [ -f "frontend/dist/index.html" ]; then
        echo "npm not detected on host, but frontend/dist/ already exists. Proceeding."
    else
        echo "WARNING: npm not found and frontend/dist/ is missing."
        echo "Please install nodejs/npm on the host or build frontend before running Caddy."
    fi
fi

# ------------------------------------------------------------------------------
# 7. Launch Full Production Stack (Backend + Caddy Reverse Proxy)
# ------------------------------------------------------------------------------
echo ""
echo "=== Step 6: Launching Full Stack (Caddy + Backend + DB) ==="
docker compose -f docker-compose.yml --profile prod up -d --build

echo ""
echo "=========================================================="
echo " DualLens Deployment Succeeded!"
echo "=========================================================="
echo "Services status:"
docker compose ps
echo ""
echo "Site URL: ${SITE_ADDRESS:-http://localhost}"
echo "To view backend logs: docker compose logs -f backend"
echo "To view proxy logs:   docker compose logs -f proxy"
echo "=========================================================="
