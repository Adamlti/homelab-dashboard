"""Local project SQLite backup evidence, not a claim about off-host backups."""
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class BackupRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1, max_length=255)
    completed_at: AwareDatetime
    size_bytes: int = Field(gt=0)
    mtime_ns: int = Field(gt=0)
    restore_checked_at: AwareDatetime | None = None
    offhost_verified_at: AwareDatetime | None = None

    @field_validator('filename')
    @classmethod
    def filename_only(cls, value):
        if value in ('.', '..') or '/' in value or '\\' in value:
            raise ValueError('A basename is required')
        return value


class BackupStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    last_attempt_at: AwareDatetime
    last_attempt_ok: bool
    last_success: BackupRecord | None = None


def status_path():
    return Path(os.getenv('DASHBOARD_BACKUP_STATUS_PATH', str(Path(__file__).resolve().parents[3] / 'data/backups/latest-backup.json')))


def load_status(path):
    if path.stat().st_size > 8192:
        raise ValueError('Backup status too large')
    return BackupStatus.model_validate_json(path.read_text())


def record_attempt(path, destination=None, now=None, *, restore_checked_at=None, offhost_verified_at=None):
    now = now or datetime.now(timezone.utc)
    try:
        previous = load_status(path).last_success
    except FileNotFoundError:
        previous = None
    if destination is not None:
        if destination.resolve() == path.resolve():
            raise ValueError('Backup destination cannot be the status filename')
        if destination.resolve().parent != path.resolve().parent:
            raise ValueError('Backup and status must share a directory')
        info = destination.stat()
        previous = BackupRecord(filename=destination.name, completed_at=now, size_bytes=info.st_size, mtime_ns=info.st_mtime_ns, restore_checked_at=restore_checked_at, offhost_verified_at=offhost_verified_at)
    status = BackupStatus(last_attempt_at=now, last_attempt_ok=destination is not None, last_success=previous)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.backup-status-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(status.model_dump_json() + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_backup_status(path=None, now=None):
    now = now or datetime.now(timezone.utc)
    path = path or status_path()
    try:
        status = load_status(path)
    except FileNotFoundError:
        return {'status': 'unknown', 'detail': 'No project backup has been recorded by the backup helper'}
    except (OSError, ValueError):
        return {'status': 'unknown', 'detail': 'Project backup status is unreadable or invalid'}
    result = status.model_dump(mode='json')
    last = status.last_success
    state, detail = 'failed', 'The last backup attempt failed'
    if last:
        age = (now - last.completed_at).total_seconds()
        result['age_seconds'] = max(0, round(age, 1))
        try:
            artifact = path.parent / last.filename
            info = artifact.stat()
            matches = artifact.is_file() and not artifact.is_symlink() and info.st_size == last.size_bytes and info.st_mtime_ns == last.mtime_ns
        except OSError:
            matches = False
        if not matches:
            state, detail = 'missing_or_changed', 'The recorded backup is missing or has changed since verification'
        elif age < -5:
            state, detail = 'unknown', 'Backup timestamp is in the future; check server time'
        elif not status.last_attempt_ok:
            state, detail = 'failed', 'Last attempt failed; the previous successful backup is retained'
        elif age > 86400:
            state, detail = 'stale', 'Last successful project backup is more than 24 hours old'
        else:
            state, detail = 'current', 'Project SQLite backup verified when created'
    result.update(status=state, detail=detail)
    return result
