#!/usr/bin/env python3
"""Single-EC2 temporary deploy controller for private RDS and DVC snapshots.

Required: run as root; Python deps in /opt/movie-recs/venv;
trusted repo under /opt/movie-recs/movie_recommendation_system.
Neither database credentials nor DagsHub credentials are ever sent from GitHub.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote

import psycopg
from psycopg import sql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
STATE = Path('/var/lib/movie-recs/deploy-state.json')
SECRETS_FILE = Path(os.environ.get('MOVIE_DEPLOY_ENV', '/etc/movie-recs/deploy.env'))
CA = Path('/etc/movie-recs/global-bundle.pem')
SLOTS = ('moviedb_blue', 'moviedb_green')
COMPOSE = ROOT / 'compose.ec2.yml'
BACKUP = ROOT / 'database/moviedb.sql.gz'
BACKUP_DVC = ROOT / 'database/moviedb.sql.gz.dvc'
ARTIFACT_DVC = ROOT / 'backend/artifacts/v1.dvc'
CHROMA_DVC = ROOT / 'backend/chroma_data.dvc'


def say(message: str):
    print(message, flush=True)


def load_secrets() -> dict[str, str]:
    if not SECRETS_FILE.is_file():
        raise RuntimeError(f'Missing EC2-only secrets file: {SECRETS_FILE}')
    if SECRETS_FILE.stat().st_mode & 0o077:
        raise RuntimeError(f'Secrets file must be mode 600: {SECRETS_FILE}')
    data = {k: v for k, v in dotenv_values(SECRETS_FILE).items() if v is not None}
    required = ('RDS_HOST', 'RDS_ADMIN_USER', 'RDS_ADMIN_PASSWORD', 'RDS_APP_USER',
                'RDS_APP_PASSWORD', 'DAGSHUB_USER', 'DAGSHUB_TOKEN', 'GEMINI_API_KEY',
                'ALLOWED_HOSTS', 'CORS_ORIGINS')
    for key in required:
        if not data.get(key) or data[key].startswith('REPLACE_') or 'XXXXXXXX' in data[key]:
            raise RuntimeError(f'Configure {key} in {SECRETS_FILE}')
    for key in ('ALLOWED_HOSTS', 'CORS_ORIGINS'):
        values = json.loads(data[key])
        if not isinstance(values, list) or not values or not all(isinstance(x, str) for x in values):
            raise RuntimeError(f'{key} must be a JSON list of strings')
    if data['RDS_APP_USER'] == data['RDS_ADMIN_USER']:
        raise RuntimeError('Use different PostgreSQL users for administration and the app')
    if not CA.is_file():
        raise RuntimeError(f'Missing RDS trust bundle: {CA}')
    return data


def dvc_md5(path: Path) -> str:
    match = re.search(r'^\s*-?\s*md5:\s*([0-9a-f]{32}(?:\.dir)?)\s*$',
                      path.read_text(), re.M)
    if not match:
        raise RuntimeError(f'Cannot read DVC content hash from {path}')
    return match.group(1)


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.is_file() else {}


def save_state(state: dict):
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = STATE.with_suffix('.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(state, out, indent=2, sort_keys=True)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, STATE)
    finally:
        temp.unlink(missing_ok=True)


def call(cmd: list[str], *, env: dict | None = None, cwd: Path = ROOT):
    # Never log arguments: DVC credential configuration can contain secrets.
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def admin_connect(s: dict, db: str = 'postgres'):
    return psycopg.connect(
        host=s['RDS_HOST'], port=int(s.get('RDS_PORT', '5432')),
        dbname=db, user=s['RDS_ADMIN_USER'], password=s['RDS_ADMIN_PASSWORD'],
        sslmode='verify-full', sslrootcert=str(CA), connect_timeout=12,
        autocommit=True,
    )


def database_exists(s: dict, db: str) -> bool:
    with admin_connect(s) as conn, conn.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (db,))
        return cur.fetchone() is not None


def provision_role(s: dict, *, initial: bool):
    with admin_connect(s) as conn, conn.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (s['RDS_APP_USER'],))
        if cur.fetchone():
            if initial:
                cur.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(
                    sql.Identifier(s['RDS_APP_USER']), sql.Literal(s['RDS_APP_PASSWORD'])))
        else:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(s['RDS_APP_USER']), sql.Literal(s['RDS_APP_PASSWORD'])))


def rebuild_inactive_database(s: dict, inactive: str):
    say(f'Recreating inactive database {inactive} (active database remains untouched)')
    with admin_connect(s) as conn, conn.cursor() as cur:
        if database_exists(s, inactive):
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(inactive)))
        cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(inactive)))


def setup_app_grants(s: dict, db: str):
    with admin_connect(s) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db)))
        cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
            sql.Identifier(db), sql.Identifier(s['RDS_APP_USER'])))
    with admin_connect(s, db) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(s['RDS_APP_USER'])))
        cur.execute(sql.SQL('GRANT SELECT ON TABLE public.movies, public.tag_lookup TO {}').format(
            sql.Identifier(s['RDS_APP_USER'])))
        cur.execute(sql.SQL('ALTER ROLE {} SET statement_timeout = {}').format(
            sql.Identifier(s['RDS_APP_USER']), sql.Literal('15s')))


def postgres_env(s: dict, db: str) -> dict:
    return {
        **os.environ,
        'PGHOST': s['RDS_HOST'], 'PGPORT': s.get('RDS_PORT', '5432'),
        'PGUSER': s['RDS_ADMIN_USER'], 'PGPASSWORD': s['RDS_ADMIN_PASSWORD'],
        'PGDATABASE': db, 'PGSSLMODE': 'verify-full',
        'PGSSLROOTCERT': '/rds-ca.pem',
    }


def restore_dump(s: dict, db: str):
    if not BACKUP.is_file():
        raise RuntimeError('Missing gzip SQL backup after DVC pull')
    with gzip.open(BACKUP, 'rb') as stream:
        header = stream.read(2048)
    if b'PostgreSQL database dump' not in header:
        raise RuntimeError('Expected a plain PostgreSQL pg_dump, not custom-format or arbitrary SQL')
    say('Checking gzip integrity before touching the inactive database')
    call(['gzip', '-t', str(BACKUP)])
    rebuild_inactive_database(s, db)
    say('Streaming trusted SQL dump into inactive RDS database')
    env = postgres_env(s, db)
    # The postgres:18 container supplies PostgreSQL 18 psql (including \restrict support).
    client = [
        'docker', 'run', '--rm', '-i', '--network', 'host',
        '-e', 'PGHOST', '-e', 'PGPORT', '-e', 'PGUSER', '-e', 'PGPASSWORD',
        '-e', 'PGDATABASE', '-e', 'PGSSLMODE', '-e', 'PGSSLROOTCERT',
        '-v', f'{CA}:/rds-ca.pem:ro', 'postgres:18',
        'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q',
    ]
    filtering = [sys.executable, str(ROOT / 'deploy/aws/pgdump_filter.py'), str(BACKUP)]
    with subprocess.Popen(filtering, stdout=subprocess.PIPE, cwd=ROOT) as pre:
        assert pre.stdout is not None
        with subprocess.Popen(client, stdin=pre.stdout, env=env, cwd=ROOT) as restore:
            pre.stdout.close()
            rc_restore = restore.wait()
        rc_filter = pre.wait()
    if rc_filter != 0 or rc_restore != 0:
        raise RuntimeError(f'PostgreSQL restore failed: filter={rc_filter}, psql={rc_restore}')


def validate_database(s: dict, db: str):
    say(f'Validating {db}: movies, tag_lookup, pg_trgm, and sample SQL')
    with admin_connect(s, db) as conn, conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM public.movies')
        movies = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM public.tag_lookup')
        tags = cur.fetchone()[0]
        if movies < 1000 or tags < 100:
            raise RuntimeError(f'Suspicious record counts: movies={movies}, tag_lookup={tags}')
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        if cur.fetchone() is None:
            raise RuntimeError('pg_trgm extension is missing: fuzzy tag search needs similarity()')
        cur.execute("SELECT similarity('hello', 'hallo')")
        cur.execute('SELECT id, title, release_date FROM public.movies LIMIT 1')
        if cur.fetchone() is None:
            raise RuntimeError('movies lacks sample rows')
        cur.execute('SELECT tag_type, name, movie_count FROM public.tag_lookup LIMIT 1')
        if cur.fetchone() is None:
            raise RuntimeError('tag_lookup lacks sample rows')
        say(f'Validation passed: movies={movies:,}, tag_lookup={tags:,}')


def download_assets(s: dict, initial: bool):
    say('Configuring DagsHub HTTPS basic auth in local (untracked) DVC config')
    # Never write live Chroma SQLite files through hardlinked DVC cache entries.
    call(['dvc', 'config', '--local', 'cache.type', 'copy'])
    call(['dvc', 'remote', 'modify', '--local', 'origin', 'auth', 'basic'])
    call(['dvc', 'remote', 'modify', '--local', 'origin', 'user', s['DAGSHUB_USER']])
    call(['dvc', 'remote', 'modify', '--local', 'origin', 'password', s['DAGSHUB_TOKEN']])
    local_cfg = ROOT / '.dvc/config.local'
    if local_cfg.exists():
        local_cfg.chmod(0o600)
    targets = ['database/moviedb.sql.gz.dvc']
    if initial:
        targets += ['backend/artifacts/v1.dvc', 'backend/chroma_data.dvc']
    say('DVC pull: ' + ', '.join(targets))
    call(['dvc', 'pull', *targets])
    if initial:
        if not (ROOT / 'backend/artifacts/v1').is_dir():
            raise RuntimeError('Recommendation artifacts missing')
        chroma_data = ROOT / 'backend/chroma_data'
        if not chroma_data.is_dir() or not (chroma_data / 'chroma.sqlite3').is_file():
            raise RuntimeError('DVC ChromaDB collection missing chroma.sqlite3')


def compose_env(s: dict, db: str) -> dict:
    def encoded(value: str) -> str:
        return quote(value, safe='')
    url = (
        f"postgresql://{encoded(s['RDS_APP_USER'])}:{encoded(s['RDS_APP_PASSWORD'])}"
        f"@{s['RDS_HOST']}:{s.get('RDS_PORT', '5432')}/{db}"
        '?sslmode=verify-full&sslrootcert=%2Frds-ca.pem'
    )
    return {
        **os.environ, 'DATABASE_URL': url, 'GEMINI_API_KEY': s['GEMINI_API_KEY'],
        'SITE_ADDRESS': s.get('SITE_ADDRESS', ':80'),
        'ALLOWED_HOSTS': s['ALLOWED_HOSTS'], 'CORS_ORIGINS': s['CORS_ORIGINS'],
        'FORWARDED_ALLOW_IPS': s.get('FORWARDED_ALLOW_IPS', '127.0.0.1'),
        'LOG_LEVEL': s.get('LOG_LEVEL', 'INFO'),
    }


def compose(cmd: list[str], env: dict):
    call(['docker', 'compose', '-f', str(COMPOSE), *cmd], env=env)


def frontend_build_if_needed(previous_sha: str | None):
    frontend_dist = ROOT / 'frontend/dist/index.html'
    changed = not frontend_dist.is_file()
    if previous_sha and not changed:
        result = subprocess.run(['git', 'diff', '--quiet', previous_sha, 'HEAD', '--', 'frontend'], cwd=ROOT)
        changed = result.returncode != 0
    if changed:
        say('Building Vite frontend using Node 22 Docker image')
        call(['docker', 'run', '--rm', '-v', f'{ROOT / "frontend"}:/work',
              '-w', '/work', 'node:22-alpine', 'sh', '-ec', 'npm ci && npm run build'])


def check_backend_health(env: dict, max_wait: int = 360):
    say('Waiting for FastAPI readiness and DB-backed search endpoints')
    # Checks internal service directly; Caddy routes /api/* but not /health.
    test = r'''import json, urllib.parse, urllib.request
base = 'http://127.0.0.1:8000'
for path in ['/health', '/api/movies/search?q=matrix&limit=1', '/api/tags/search?q=action&types=genres']:
    with urllib.request.urlopen(base + path, timeout=15) as response:
        obj = json.load(response)
        assert response.status == 200
        if path == '/health': assert obj.get('status') == 'ok'
        else: assert isinstance(obj, list)
'''
    end = time.monotonic() + max_wait
    while time.monotonic() < end:
        result = subprocess.run([
            'docker', 'compose', '-f', str(COMPOSE), 'exec', '-T',
            'backend', 'python', '-c', test,
        ], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            say('FastAPI database-backed health tests passed')
            return
        time.sleep(10)
    raise RuntimeError('FastAPI did not pass readiness + movies/tags checks within 360 seconds')


def deploy_image(s: dict, database: str, old_database: str | None):
    new_env = compose_env(s, database)
    old_env = compose_env(s, old_database) if old_database else None
    old_image = subprocess.run(
        ['docker', 'image', 'inspect', 'movie-recs-backend:current'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if old_image:
        call(['docker', 'tag', 'movie-recs-backend:current', 'movie-recs-backend:rollback'])
    try:
        compose(['build', 'backend'], new_env)
        compose(['up', '-d', '--no-build', '--force-recreate', 'backend', 'proxy'], new_env)
        check_backend_health(new_env)
        # In addition to API readiness, verify that Caddy's configured reverse proxy is valid.
        compose(['exec', '-T', 'proxy', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile'], new_env)
    except Exception:
        say('Cutover failed. Attempting automatic backend rollback...')
        if old_env and old_image:
            call(['docker', 'tag', 'movie-recs-backend:rollback', 'movie-recs-backend:current'])
            compose(['up', '-d', '--no-build', '--force-recreate', 'backend', 'proxy'], old_env)
            check_backend_health(old_env)
            say(f'Rollback validated: active database is still {old_database}')
        else:
            say('No previous healthy backend image/database available: manual recovery required')
        raise


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run via sudo or SSM as root (protected secrets/state)')
    s = load_secrets()
    current_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    state = load_state()
    pw_fingerprint = hashlib.sha256(s['RDS_APP_PASSWORD'].encode()).hexdigest()
    if state.get('active_db') and state.get('app_password_sha256') != pw_fingerprint:
        raise RuntimeError('App database password changed or state lacks fingerprint. Rotate passwords separately; refusing live deployment.')
    old = state.get('active_db')
    if old and old not in SLOTS:
        raise RuntimeError('Unexpected active database in state file; refusing to replace anything')
    if not old and any(database_exists(s, name) for name in SLOTS):
        raise RuntimeError('Existing blue/green DB found without state. Refusing automatic first deployment.')
    backup_hash = dvc_md5(BACKUP_DVC)
    artifact_hash = dvc_md5(ARTIFACT_DVC)
    chroma_hash = dvc_md5(CHROMA_DVC)
    # Replacing embedded artifacts/Chroma while the current backend is using them is unsafe.
    if old and (artifact_hash != state.get('artifact_md5') or chroma_hash != state.get('chroma_md5')):
        raise RuntimeError('ML artifacts or Chroma DVC hash changed. Stop automatic DB-only deploy; migrate artifacts as a separate release.')
    if old and backup_hash == state.get('backup_md5') and current_sha == state.get('git_sha'):
        say('Same source commit and same deployed backup hash; no action required')
        return
    stage = next(name for name in SLOTS if name != old)
    db_changed = not old or backup_hash != state.get('backup_md5')
    say(f'Current active database: {old or "none"}. Target: {stage if db_changed else old}')
    # Build and validate the frontend before changing the inactive database.
    frontend_build_if_needed(os.environ.get('PREVIOUS_SOURCE_SHA'))
    if db_changed:
        download_assets(s, initial=not old)
        provision_role(s, initial=not old)
        restore_dump(s, stage)
        validate_database(s, stage)
        setup_app_grants(s, stage)
        target = stage
    else:
        target = old
    deploy_image(s, target, old)
    # This state file is the promotion marker. Only write AFTER successful app health.
    # If a disk/state write fails after cutover, return to old backend and old database.
    promoted = {
        'active_db': target,
        'backup_md5': backup_hash,
        'artifact_md5': artifact_hash,
        'chroma_md5': chroma_hash,
        'git_sha': current_sha,
        'app_password_sha256': pw_fingerprint,
        'previous_active_db': old,
        'previous_backup_md5': state.get('backup_md5') if old else None,
        'previous_git_sha': state.get('git_sha') if old else None,
    }
    try:
        save_state(promoted)
    except Exception:
        if old:
            say('Promotion marker failed; attempting to restore old backend/db')
            call(['docker', 'tag', 'movie-recs-backend:rollback', 'movie-recs-backend:current'])
            previous_env = compose_env(s, old)
            compose(['up', '-d', '--no-build', '--force-recreate', 'backend', 'proxy'], previous_env)
            check_backend_health(previous_env)
        raise
    say(f'PROMOTED: {target}; previous database retained as rollback slot')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'DEPLOYMENT_FAILED: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
