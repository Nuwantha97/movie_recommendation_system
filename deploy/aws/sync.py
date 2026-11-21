#!/usr/bin/env python3
"""Deploy the selected DVC snapshots and backend release on EC2."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import quote

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
DATA = Path('/var/lib/movie-recs')
RELEASES = Path('/opt/movie-recs/releases')
LEGACY_REPO = Path('/opt/movie-recs/movie_recommendation_system')
CA = Path('/etc/movie-recs/global-bundle.pem')
DEPLOY_ENV = Path('/etc/movie-recs/deploy.env')
SLOTS = ('moviedb_blue', 'moviedb_green')
COMPOSE = ROOT / 'compose.ec2.yml'
BACKUP = ROOT / 'database/moviedb.sql.gz'
BACKUP_DVC = ROOT / 'database/moviedb.sql.gz.dvc'
ARTIFACT_DVC = ROOT / 'backend/artifacts/v1.dvc'
CHROMA_DVC = ROOT / 'backend/chroma_data.dvc'


def say(message: str):
    print(message, flush=True)


def read_secret(secret_id: str) -> str:
    raw = subprocess.check_output(['aws', 'secretsmanager', 'get-secret-value',
                                   '--secret-id', secret_id, '--query', 'SecretString',
                                   '--output', 'text'])
    return raw.decode('utf-8-sig')


def env_values(text: str) -> dict:
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            raise ValueError(f'Invalid KEY=value on deploy.env line {number}')
        value = value.strip()
        if len(value) >= 2 and value[0] in ("\"", "'") and value[-1] == value[0]:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_secrets() -> dict:
    admin = json.loads(read_secret(os.environ['MASTER_SECRET_ARN']))
    if DEPLOY_ENV.exists():
        info = DEPLOY_ENV.stat()
        if info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError(f'{DEPLOY_ENV} must be owned by root and private (chmod 600)')
        runtime = env_values(DEPLOY_ENV.read_text(encoding='utf-8-sig'))
    else:
        raw = read_secret(os.environ['RUNTIME_SECRET_NAME'])
        runtime = json.loads(raw) if raw.lstrip().startswith('{') else env_values(raw)
    keys = ('RDS_APP_PASSWORD', 'DAGSHUB_USER', 'DAGSHUB_TOKEN', 'GEMINI_API_KEY')
    for key in keys:
        if not isinstance(runtime.get(key), str) or not runtime[key]:
            raise ValueError(f'Missing {key} in the runtime secret')
    user = runtime.get('RDS_APP_USER', 'app_ro')
    if user == admin['username']:
        raise ValueError('The application role must be separate from the RDS admin')
    return {**{key: runtime[key] for key in keys}, 'RDS_APP_USER': user,
            'RDS_ADMIN_USER': admin['username'], 'RDS_ADMIN_PASSWORD': admin['password'],
            'RDS_HOST': os.environ['RDS_HOST'], 'RDS_PORT': os.environ['RDS_PORT']}


def dvc_md5(path: Path) -> str:
    match = re.search(r'^\s*-?\s*md5:\s*([0-9a-f]{32}(?:\.dir)?)\s*$',
                      path.read_text(), re.M)
    if not match:
        raise RuntimeError(f'Cannot read DVC content hash from {path}')
    return match.group(1)


def save_state(conn, state: dict):
    conn.execute('INSERT INTO public.movie_recs_deployment (id, state) VALUES (1, %s) '
                 'ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state', (Jsonb(state),))


def load_state(conn, secrets: dict) -> dict:
    # The admin database retains the active slot even when EC2 is replaced.
    conn.execute('CREATE TABLE IF NOT EXISTS public.movie_recs_deployment '
                 '(id integer PRIMARY KEY CHECK (id = 1), state jsonb NOT NULL)')
    row = conn.execute('SELECT state FROM public.movie_recs_deployment WHERE id = 1').fetchone()
    if row:
        return row[0]
    legacy = DATA / 'deploy-state.json'
    state = json.loads(legacy.read_text()) if legacy.is_file() else {}
    occupied = [db for db in SLOTS if database_exists(secrets, db)]
    if occupied and state.get('active_db') not in occupied:
        raise RuntimeError('Existing RDS slots have no matching deployment record')
    if state and state.get('active_db') not in occupied:
        raise RuntimeError('Local deployment record does not match this RDS instance')
    # Claim the empty slots before the first restore so a failed import is retryable.
    save_state(conn, state)
    return state


def call(cmd: list[str], *, env: dict | None = None, cwd: Path = ROOT):
    # Never log arguments: DVC credential configuration can contain secrets.
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode:
        raise RuntimeError(f'{cmd[0]} exited with status {result.returncode}')


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


def provision_role(s: dict):
    with admin_connect(s) as conn, conn.cursor() as cur:
        cur.execute('SELECT rolcanlogin FROM pg_roles WHERE rolname = %s', (s['RDS_APP_USER'],))
        role = cur.fetchone()
        if role is None:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(s['RDS_APP_USER']), sql.Literal(s['RDS_APP_PASSWORD'])))
        elif not role[0]:
            raise RuntimeError('The configured application role already exists without LOGIN')


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
        cur.execute(sql.SQL('ALTER ROLE {} IN DATABASE {} SET statement_timeout = {}').format(
            sql.Identifier(s['RDS_APP_USER']), sql.Identifier(db), sql.Literal('15s')))


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


def prepare_assets(s: dict, candidate: dict, restore: bool):
    # Each DVC pointer is checked out in this release, then atomically published.
    # Writable Chroma data must never share inodes with the DVC cache.
    assets = DATA / 'assets'
    assets.mkdir(mode=0o700, exist_ok=True)
    pulls = []
    for pointer, key, sentinel in (
        (ARTIFACT_DVC, 'artifact_md5', 'tag_matrix.npz'),
        (CHROMA_DVC, 'chroma_md5', 'chroma.sqlite3'),
    ):
        dest = assets / candidate[key]
        if not (dest / sentinel).is_file():
            pulls.append((pointer, dest, sentinel))
    targets = [str(path.relative_to(ROOT)) for path, _, _ in pulls]
    if restore:
        targets.append(str(BACKUP_DVC.relative_to(ROOT)))
    if not targets:
        return
    dvc = [sys.executable, '-m', 'dvc']
    call([*dvc, 'config', '--local', 'cache.type', 'copy'])
    config = ROOT / '.dvc/config.local'
    try:
        for key, value in [('auth', 'basic'), ('user', s['DAGSHUB_USER']),
                           ('password', s['DAGSHUB_TOKEN'])]:
            call([*dvc, 'remote', 'modify', '--local', 'origin', key, value])
        call([*dvc, 'pull', '--force', *targets])
        for pointer, dest, sentinel in pulls:
            src = pointer.with_suffix('')
            if not (src / sentinel).is_file():
                raise RuntimeError(f'Missing {sentinel} from {pointer.name}')
            src.rename(dest)
    finally:
        config.unlink(missing_ok=True)
        shutil.rmtree(ROOT / '.dvc/cache', ignore_errors=True)


def compose_env(s: dict, release: dict) -> dict:
    user = quote(s['RDS_APP_USER'], safe='')
    password = quote(s['RDS_APP_PASSWORD'], safe='')
    db = release['active_db']
    site = release.get('site', os.environ['SITE_ADDRESS'])
    url = (f"postgresql://{user}:{password}@{s['RDS_HOST']}:{s['RDS_PORT']}/{db}"
           "?sslmode=verify-full&sslrootcert=%2Frds-ca.pem")
    return {
        **os.environ, 'DATABASE_URL': url, 'GEMINI_API_KEY': s['GEMINI_API_KEY'],
        'ALLOWED_HOSTS': json.dumps([site.removeprefix('http://'), '127.0.0.1', 'localhost']),
        'CADDYFILE': 'Caddyfile.cloudfront' if site.startswith('http://') else 'Caddyfile',
        'SITE_ADDRESS': site, 'CORS_ORIGINS': release.get('origins', os.environ['CORS_ORIGINS']),
        'RELEASE_SHA': release['git_sha'],
        'ARTIFACT_PATH': str(DATA / 'assets' / release['artifact_md5']),
        'CHROMA_PATH': str(DATA / 'assets' / release['chroma_md5']),
    }


def compose_args(root: Path) -> list[str]:
    return ['docker', 'compose', '-f', str(root / 'compose.ec2.yml')]


def image_exists(tag: str) -> bool:
    return subprocess.run(['docker', 'image', 'inspect', tag], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def start_and_check(root: Path, env: dict):
    cmd = compose_args(root)
    call(cmd + ['up', '-d', '--no-build', 'backend', 'proxy'], env=env)
    say('Waiting for FastAPI warmup and database-backed searches')
    test = """import json, urllib.request
for path in ['/health', '/api/movies/search?q=matrix&limit=1', '/api/tags/search?q=action&types=genres']:
    with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=15) as response:
        value = json.load(response)
        assert value == {'status': 'ok'} if path == '/health' else isinstance(value, list) and value
"""
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        if subprocess.run(cmd + ['exec', '-T', 'backend', 'python', '-c', test],
                          env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(10)
    else:
        raise RuntimeError('Backend readiness timed out. Inspect docker logs movies_backend')
    call(cmd + ['exec', '-T', 'proxy', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile'], env=env)
    if root != LEGACY_REPO:
        site = env['SITE_ADDRESS']
        origin = site if site.startswith('http://') else f'https://{site}'
        host = origin.split('://', 1)[1]
        port = 80 if site.startswith('http://') else 443
        call(['curl', '--fail', '--silent', '--show-error', '--output', '/dev/null',
              '--resolve', f'{host}:{port}:127.0.0.1', '--retry', '24', '--retry-delay', '5',
              '--retry-all-errors', '--max-time', '12', f'{origin}/health'])


def rollback(s: dict, state: dict):
    if state.get('active_db'):
        old_root = RELEASES / state['git_sha']
        tag = state['git_sha']
        if not old_root.is_dir() and 'site' not in state and LEGACY_REPO.is_dir():
            old_root = LEGACY_REPO
            tag = 'current'
        if old_root.is_dir() and image_exists('movie-recs-backend:' + tag):
            say(f"Restoring release {state['git_sha']} on {state['active_db']}")
            start_and_check(old_root, compose_env(s, state))
            return
    # Fresh or replacement host without a previous image. Stop any failed candidate.
    call(['docker', 'compose', '-f', str(COMPOSE), 'stop', 'proxy', 'backend'],
         env=compose_env(s, state['pending']))


def cleanup(candidate: dict, previous: dict):
    keep = [item for item in (candidate, previous) if item.get('git_sha')]
    hashes = {item[key] for item in keep for key in ('artifact_md5', 'chroma_md5')}
    for path in (DATA / 'assets').iterdir():
        if re.fullmatch(r'[a-f0-9]{32}\.dir', path.name) and path.name not in hashes:
            shutil.rmtree(path)
    for path in RELEASES.iterdir():
        if re.fullmatch(r'[a-f0-9]{40}', path.name) and all(path.name != x['git_sha'] for x in keep):
            shutil.rmtree(path)
            subprocess.run(['docker', 'image', 'rm', 'movie-recs-backend:' + path.name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def deploy(conn, s: dict):
    state = load_state(conn, s)
    old = state.get('active_db')
    digest = hashlib.sha256(s['RDS_APP_PASSWORD'].encode()).hexdigest()
    if old and (old not in SLOTS or digest != state.get('app_password_sha256')
                or state.get('app_user', s['RDS_APP_USER']) != s['RDS_APP_USER']):
        raise RuntimeError('Check the active slot and application login before deploying')
    if 'pending' in state:
        rollback(s, state)
        state.pop('pending')
        save_state(conn, state)
    backup = dvc_md5(BACKUP_DVC)
    restore = not old or state.get('backup_md5') != backup
    target = next(db for db in SLOTS if db != old) if restore else old
    candidate = dict(active_db=target, backup_md5=backup, git_sha=os.environ['RELEASE_SHA'],
                     artifact_md5=dvc_md5(ARTIFACT_DVC), chroma_md5=dvc_md5(CHROMA_DVC),
                     app_user=s['RDS_APP_USER'], app_password_sha256=digest, site=os.environ['SITE_ADDRESS'],
                     origins=os.environ['CORS_ORIGINS'])
    env = compose_env(s, candidate)
    prepare_assets(s, candidate, restore)
    if restore:
        provision_role(s)
        restore_dump(s, target)
        validate_database(s, target)
        setup_app_grants(s, target)
        BACKUP.unlink()
    image = 'movie-recs-backend:' + candidate['git_sha']
    if not image_exists(image):
        call(['docker', 'build', '--build-arg', 'CPU_ONLY=true', '-t', image, 'backend'])
    pending = {**state, 'pending': candidate}
    save_state(conn, pending)
    try:
        start_and_check(ROOT, env)
    except Exception:
        rollback(s, pending)
        save_state(conn, state)
        raise
    save_state(conn, candidate)
    say(f"Promoted {candidate['git_sha']} using {target}")
    cleanup(candidate, state)


def main():
    s = load_secrets()
    with admin_connect(s) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(192047, 1)").fetchone()[0]:
            raise RuntimeError('Another RDS deployment is in progress')
        deploy(conn, s)


if __name__ == '__main__':
    main()
