"""Exercise release decisions without AWS credentials or a running database."""
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import cloudflare
import sync

load_persisted_state = sync.load_state
original_start_and_check = sync.start_and_check


class ArtifactTests(unittest.TestCase):
    def test_chroma_update_downloads_only_changed_pointer_and_reuses_artifacts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            artifacts = data / 'assets' / 'artifacts-hash'
            artifacts.mkdir(parents=True)
            (artifacts / 'tag_matrix.npz').touch()
            (root / '.dvc').mkdir()
            model = root / 'backend/artifacts/v1.dvc'
            chroma = root / 'backend/chroma_data.dvc'
            model.parent.mkdir(parents=True)
            model.touch()
            chroma.touch()
            def run(cmd):
                if 'pull' in cmd:
                    self.assertEqual(cmd[cmd.index('pull') + 1:], ['--force', str(chroma.relative_to(root))])
                    out = chroma.with_suffix('')
                    out.mkdir()
                    (out / 'chroma.sqlite3').touch()
                else:
                    (root / '.dvc/config.local').touch()
            with patch.multiple(sync, ROOT=root, DATA=data, ARTIFACT_DVC=model, CHROMA_DVC=chroma), \
                 patch.object(sync, 'call', side_effect=run) as command:
                release = dict(artifact_md5='artifacts-hash', chroma_md5='chroma-hash')
                sync.prepare_assets(dict(DAGSHUB_USER='user', DAGSHUB_TOKEN='token'), release, False)
                self.assertTrue((data / 'assets/chroma-hash/chroma.sqlite3').is_file())
                self.assertFalse((root / '.dvc/config.local').exists())
                command.reset_mock()
                sync.prepare_assets({}, release, False)
                command.assert_not_called()


class CloudflareTests(unittest.TestCase):
    def test_first_deploy_uses_assigned_pages_domain_and_creates_api_record(self):
        with TemporaryDirectory() as tmp:
            envfile = Path(tmp) / 'env'
            env = dict(GITHUB_ENV=str(envfile), PAGES_PROJECT='movies', CLOUDFLARE_ACCOUNT_ID='account',
                       CLOUDFLARE_ZONE_ID='zone', VITE_API_BASE='https://api.example.com/api',
                       FRONTEND_ORIGIN='', EC2_PUBLIC_IP='192.0.2.1')
            project = dict(production_branch='main', subdomain='movies-abc.pages.dev')
            with patch.dict(os.environ, env), patch.object(cloudflare, 'api',
                                                          side_effect=[None, project, [], {}]) as api:
                cloudflare.main()
            self.assertIn('FRONTEND_ORIGIN=https://movies-abc.pages.dev', envfile.read_text())
            path, method, record = api.call_args.args
            self.assertEqual((path, method), ('zones/zone/dns_records', 'POST'))
            self.assertEqual(record['name'], 'api.example.com')
            self.assertFalse(record['proxied'])


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.secrets = dict(RDS_APP_PASSWORD='pw', RDS_APP_USER='app_ro', RDS_PORT='5432',
                            RDS_HOST='db.example', GEMINI_API_KEY='key')
        self.enterContext(patch.dict(os.environ, RELEASE_SHA='a' * 40,
                                     SITE_ADDRESS='api.example', CORS_ORIGINS='["https://ui.example"]'))
        self.old = dict(active_db=sync.SLOTS[0], backup_md5=sync.dvc_md5(sync.BACKUP_DVC),
                        artifact_md5='1' * 32 + '.dir', chroma_md5='2' * 32 + '.dir',
                        git_sha='b' * 40, app_password_sha256=hashlib.sha256(b'pw').hexdigest())
        mocks = ['load_state', 'save_state', 'prepare_assets', 'provision_role', 'restore_dump',
                 'validate_database', 'setup_app_grants', 'call', 'start_and_check', 'rollback',
                 'cleanup']
        for name in mocks:
            setattr(self, name, self.enterContext(patch.object(sync, name)))
        self.conn = MagicMock()
        self.enterContext(patch.object(sync.subprocess, 'run', return_value=MagicMock(returncode=1)))
        self.backup = self.enterContext(patch.object(sync, 'BACKUP'))

    def test_origin_settings_and_health_check_follow_the_saved_release(self):
        for site, caddyfile, protocol, port in [
            ('http://dist.cloudfront.net', 'Caddyfile.cloudfront', 'http', 80),
            ('api.example', 'Caddyfile', 'https', 443),
        ]:
            with self.subTest(site=site):
                env = sync.compose_env(self.secrets, {**self.old, 'site': site})
                host = site.removeprefix('http://')
                self.assertEqual(env['CADDYFILE'], caddyfile)
                self.assertIn(f'"{host}"', env['ALLOWED_HOSTS'])
                with patch.object(sync.subprocess, 'run', return_value=MagicMock(returncode=0)):
                    original_start_and_check(sync.ROOT, env)
                args = self.call.call_args.args[0]
                self.assertIn(f'{host}:{port}:127.0.0.1', args)
                self.assertEqual(args[-1], f'{protocol}://{host}/health')

    def test_initial_import_promotes_only_after_health(self):
        self.load_state.return_value = {}
        self.start_and_check.side_effect = lambda *args: self.assertIn(
            'pending', self.save_state.call_args.args[1])
        sync.deploy(self.conn, self.secrets)
        self.restore_dump.assert_called_once_with(self.secrets, sync.SLOTS[0])
        self.assertEqual(self.save_state.call_args.args[1]['active_db'], sync.SLOTS[0])

    def test_model_update_keeps_database_and_selects_new_assets(self):
        self.load_state.return_value = self.old
        sync.deploy(self.conn, self.secrets)
        self.restore_dump.assert_not_called()
        _, candidate, restore = self.prepare_assets.call_args.args
        self.assertFalse(restore)
        self.assertEqual(candidate['active_db'], self.old['active_db'])
        self.assertEqual(candidate['chroma_md5'], sync.dvc_md5(sync.CHROMA_DVC))

    def test_changed_dump_and_failed_health_roll_back(self):
        self.old['backup_md5'] = '0' * 32
        self.load_state.return_value = self.old
        self.start_and_check.side_effect = RuntimeError('failed health check')
        with self.assertRaisesRegex(RuntimeError, 'failed health'):
            sync.deploy(self.conn, self.secrets)
        self.restore_dump.assert_called_once_with(self.secrets, sync.SLOTS[1])
        self.rollback.assert_called_once()
        self.assertEqual(self.save_state.call_args.args[1], self.old)
        self.cleanup.assert_not_called()

    def test_interrupted_cutover_is_reconciled_before_restore(self):
        self.load_state.return_value = {**self.old, 'pending': dict(self.old)}
        sync.deploy(self.conn, self.secrets)
        self.rollback.assert_called_once()
        self.assertNotIn('pending', self.save_state.call_args_list[0].args[1])

    def test_unmanaged_slot_without_state_is_preserved(self):
        self.conn.execute.return_value.fetchone.return_value = None
        with TemporaryDirectory() as tmp, patch.object(sync, 'DATA', Path(tmp)), \
             patch.object(sync, 'database_exists', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'no matching deployment record'):
                load_persisted_state(self.conn, self.secrets)
        self.save_state.assert_not_called()


if __name__ == '__main__':
    unittest.main()
