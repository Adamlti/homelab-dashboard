from pathlib import Path
import pytest

from app import backup_job
from app.services import tasks, roadmap
from app.services.backup_status import read_backup_status


def test_scheduled_backups_restore_and_prune_only_owned_files(tmp_path):
    tasks.initialize()
    roadmap.initialize()
    directory = tmp_path / 'backups'
    directory.mkdir()
    manual = directory / 'manual.sqlite3'
    manual.write_text('operator copy')
    target = tmp_path / 'unrelated'
    target.write_text('do not touch')
    link = directory / 'scheduled-20000101T000000000000Z-12345678.sqlite3'
    link.symlink_to(target)
    first = backup_job.run_backup(tasks.database_path(), directory, keep=1)
    second = backup_job.run_backup(tasks.database_path(), directory, keep=1)
    assert not first.exists() and second.exists()
    assert manual.read_text() == 'operator copy' and link.is_symlink()
    assert target.read_text() == 'do not touch'
    assert second.stat().st_mode & 0o077 == 0
    status = read_backup_status(directory / 'latest-backup.json')
    assert status['status'] == 'current'
    assert status['last_success']['restore_checked_at']
    assert status['last_success']['offhost_verified_at'] is None


def test_failed_restore_does_not_prune_or_record_success(tmp_path, monkeypatch):
    tasks.initialize()
    roadmap.initialize()
    first = backup_job.run_backup(tasks.database_path(), tmp_path / 'backups', keep=1)
    def fail(*args):
        raise ValueError('restore failed')
    monkeypatch.setattr(backup_job, 'restore_check', fail)
    with pytest.raises(ValueError):
        backup_job.run_backup(tasks.database_path(), first.parent, keep=1)
    status = read_backup_status(first.parent / 'latest-backup.json')
    assert first.exists() and status['status'] == 'failed'
    assert status['last_success']['filename'] == first.name


@pytest.mark.parametrize('destination', ['-oProxyCommand=bad:/tmp', 'host:/tmp/../etc', 'host:/tmp/$(bad)', 'host:/tmp/a;bad', 'file:///tmp'])
def test_offhost_rejects_command_injection(tmp_path, destination):
    with pytest.raises(ValueError):
        backup_job.offhost_copy(tmp_path / 'backup.sqlite3', destination)


def test_offhost_checksum_mismatch_is_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    backup = tmp_path / 'backup.sqlite3'
    backup.write_bytes(b'example')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout='wrong  backup.sqlite3')
    monkeypatch.setattr(backup_job.subprocess, 'run', run)
    with pytest.raises(ValueError, match='checksum'):
        backup_job.offhost_copy(backup, 'backup@host:/backups')
    assert calls[0][0] == 'rsync' and calls[1][0] == 'ssh'
    assert '--delete' not in calls[0]
