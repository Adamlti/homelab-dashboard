"""Scheduled, bounded project backups. No host commands are exposed by the API."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from uuid import uuid4

from app.project_backup import copy_database, validate
from app.services.backup_status import record_attempt

OWNED_NAME = re.compile(r'scheduled-\d{8}T\d{12}Z-[0-9a-f]{8}\.sqlite3')


def restore_check(backup):
    """Restore to an isolated database and compare every project row."""
    with tempfile.TemporaryDirectory(prefix='dashboard-restore-') as directory:
        restored = copy_database(backup, Path(directory) / 'restored.sqlite3')
        with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as original, sqlite3.connect(restored) as check:
            validate(check)
            tables = [('tasks', 'id'), ('roadmap', 'id'), ('metadata', 'key')]
            if original.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_audit'").fetchone():
                tables.append(('project_audit', 'id'))
            for table, key in tables:
                query = f'SELECT * FROM {table} ORDER BY {key}'
                if original.execute(query).fetchall() != check.execute(query).fetchall():
                    raise ValueError('Restored project rows differ from backup')


def offhost_copy(backup, destination):
    """Operator-configured SSH destination; no arbitrary command or shell interpolation."""
    if '://' in destination or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.@-]*:/[a-zA-Z0-9_./-]+', destination):
        raise ValueError('Use user@host:/absolute/directory (letters, numbers, dot, dash, underscore)')
    host, directory = destination.split(':', 1)
    if '..' in directory.split('/'):
        raise ValueError('Parent traversal is not allowed')
    remote = directory.rstrip('/') + '/' + backup.name
    subprocess.run(['rsync', '--protect-args', '--checksum', '--chmod=F600', '-e',
                    'ssh -o BatchMode=yes -o ConnectTimeout=10', '--', str(backup), host + ':' + remote],
                   check=True, timeout=120, capture_output=True)
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                             'sha256sum', '--', remote], check=True, timeout=30, capture_output=True, text=True)
    if not result.stdout.split() or result.stdout.split()[0] != hashlib.sha256(backup.read_bytes()).hexdigest():
        raise ValueError('Off-host checksum did not match')


def run_backup(source, directory, keep=30, offhost=None):
    if not 1 <= keep <= 365:
        raise ValueError('Retention must be between 1 and 365 backups')
    directory = directory.absolute()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # One owner per output directory; a failed run never prunes a previous backup.
    fd = os.open(directory / '.schedule.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = datetime.now(timezone.utc)
        destination = directory / f'scheduled-{now:%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}.sqlite3'
        try:
            copy_database(source, destination)
            restore_check(destination)
            checked_at = datetime.now(timezone.utc)
            if offhost:
                offhost_copy(destination, offhost)
            record_attempt(directory / 'latest-backup.json', destination, restore_checked_at=checked_at,
                           offhost_verified_at=datetime.now(timezone.utc) if offhost else None)
            owned = sorted((p for p in directory.iterdir() if OWNED_NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()),
                           key=lambda p: p.name, reverse=True)
            for old in owned[keep:]:
                old.unlink()
            return destination
        except Exception:
            record_attempt(directory / 'latest-backup.json')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--keep', type=int, default=30)
    parser.add_argument('--offhost', default=os.getenv('DASHBOARD_BACKUP_OFFHOST'))
    parser.add_argument('--interval-hours', type=float, help='Repeat in a dedicated backup container; omit for a timer job')
    args = parser.parse_args()
    if args.interval_hours is not None and not 1 <= args.interval_hours <= 168:
        parser.error('Interval must be between 1 and 168 hours')
    while True:
        try:
            print(run_backup(args.source, args.directory, args.keep, args.offhost), flush=True)
        except Exception as exc:
            # Do not print remote subprocess output, which can contain infrastructure details.
            print(f'Backup failed: {type(exc).__name__}', flush=True)
            if args.interval_hours is None:
                raise SystemExit(1) from exc
        if args.interval_hours is None:
            break
        time.sleep(args.interval_hours * 3600)


if __name__ == '__main__':
    main()
