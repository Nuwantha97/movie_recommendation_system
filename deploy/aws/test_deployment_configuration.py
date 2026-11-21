"""Lightweight repository-specific smoke checks (no AWS access needed)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class DeploymentConfigurationTests(unittest.TestCase):
    def test_aws_compose_separate_from_local_postgres(self):
        text = (ROOT / "compose.ec2.yml").read_text()
        self.assertIn('DATABASE_URL: ${DATABASE_URL:', text)
        self.assertNotIn('movies_database:5432', text)
        self.assertNotIn('    database:', text)
        self.assertIn('command: ["uvicorn"', text)
        self.assertIn('./backend/chroma_data:/chroma_data:rw', text)
    def test_health_check_uses_actual_tag_type(self):
        text = (ROOT / "deploy/aws/sync.py").read_text()
        self.assertIn('types=genres', text)
        self.assertNotIn('types=genre&', text)
    def test_shell_entrypoint_sets_dvc_venv_path(self):
        text = (ROOT / "deploy/aws/entrypoint.sh").read_text()
        self.assertIn('export PATH="/opt/movie-recs/venv/bin:$PATH"', text)

if __name__ == "__main__":
    unittest.main()
