"""Exercise the production import program without requiring Docker privileges."""
import importlib.util
from pathlib import Path
import subprocess
import sys

from app.project_backup import copy_database
from app.services import tasks, roadmap


def test_deploy_import_is_validated_private_and_never_overwrites(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/deploy.py'
    spec = importlib.util.spec_from_file_location('dashboard_deploy', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tasks.initialize()
    roadmap.initialize()
    backup = copy_database(tasks.database_path(), tmp_path / 'source.sqlite3')
    destination = tmp_path / 'imported.sqlite3'
    code = module.SEED.replace('/tasks/tasks.sqlite3', str(destination))
    result = subprocess.run([sys.executable, '-c', code], input=backup.read_bytes(), capture_output=True)
    assert result.returncode == 0, result.stderr
    assert destination.read_bytes() == backup.read_bytes()
    assert destination.stat().st_mode & 0o077 == 0
    result = subprocess.run([sys.executable, '-c', code], input=b'never replace an existing database', capture_output=True)
    assert result.returncode == 0
    assert destination.read_bytes() == backup.read_bytes()
    invalid = tmp_path / 'invalid.sqlite3'
    result = subprocess.run([sys.executable, '-c', module.SEED.replace('/tasks/tasks.sqlite3', str(invalid))], input=b'invalid sqlite', capture_output=True)
    assert result.returncode != 0 and not invalid.exists()
    assert not list(tmp_path.glob('.seed-*'))
