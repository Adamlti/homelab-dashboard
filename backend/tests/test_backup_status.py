from datetime import datetime, timedelta, timezone

import pytest

from app.project_backup import copy_database
from app.services import tasks, roadmap
from app.services.backup_status import BackupRecord, read_backup_status, record_attempt


def test_status_covers_current_old_failed_missing_and_changed(tmp_path):
    tasks.initialize()
    roadmap.initialize()
    now = datetime.now(timezone.utc)
    path = tmp_path / 'latest-backup.json'
    artifact = copy_database(tasks.database_path(), tmp_path / 'backup.sqlite3')
    assert read_backup_status(path)['status'] == 'unknown'
    record_attempt(path, artifact, now)
    assert read_backup_status(path, now)['status'] == 'current'
    assert read_backup_status(path, now + timedelta(hours=25))['status'] == 'stale'
    record_attempt(path, now=now + timedelta(minutes=1))
    failed = read_backup_status(path, now + timedelta(minutes=1))
    assert failed['status'] == 'failed'
    assert failed['last_success']['filename'] == artifact.name
    artifact.write_bytes(b'corrupted backup')
    assert read_backup_status(path)['status'] == 'missing_or_changed'
    artifact.unlink()
    assert read_backup_status(path)['status'] == 'missing_or_changed'


def test_invalid_status_and_unsafe_filename_rejected(tmp_path):
    path = tmp_path / 'latest-backup.json'
    path.write_text('invalid')
    assert read_backup_status(path)['status'] == 'unknown'
    with pytest.raises(ValueError):
        record_attempt(path)
    assert path.read_text() == 'invalid'
    for filename in ('../tasks.sqlite3', '/etc/passwd', 'a\\b', '..'):
        with pytest.raises(ValueError):
            BackupRecord(filename=filename, completed_at=datetime.now(timezone.utc), size_bytes=1, mtime_ns=1)


def test_future_backup_and_failed_first_attempt(tmp_path):
    path = tmp_path / 'latest-backup.json'
    record_attempt(path)
    assert read_backup_status(path)['status'] == 'failed'
    artifact = tmp_path / 'copy.sqlite3'
    artifact.write_bytes(b'test fixture')
    record_attempt(path, artifact, datetime.now(timezone.utc) + timedelta(hours=1))
    assert read_backup_status(path)['status'] == 'unknown'


def test_backup_cli_publishes_status_and_restore_does_not(tmp_path, monkeypatch):
    from app.project_backup import main
    tasks.initialize()
    roadmap.initialize()
    artifact = tmp_path / 'backup.sqlite3'
    monkeypatch.setattr('sys.argv', ['backup', 'backup', str(tasks.database_path()), str(artifact)])
    main()
    path = tmp_path / 'latest-backup.json'
    assert read_backup_status(path)['status'] == 'current'
    original = path.read_bytes()
    restored = tmp_path / 'restored.sqlite3'
    monkeypatch.setattr('sys.argv', ['backup', 'restore', str(artifact), str(restored), '--stopped'])
    main()
    assert restored.exists() and path.read_bytes() == original


def test_backup_status_never_overwrites_an_existing_backup(tmp_path, monkeypatch):
    from app.project_backup import main
    tasks.initialize()
    roadmap.initialize()
    artifact = copy_database(tasks.database_path(), tmp_path / 'latest-backup.json')
    original = artifact.read_bytes()
    monkeypatch.setattr('sys.argv', ['backup', 'backup', str(tasks.database_path()), str(artifact)])
    with pytest.raises(SystemExit):
        main()
    assert artifact.read_bytes() == original
