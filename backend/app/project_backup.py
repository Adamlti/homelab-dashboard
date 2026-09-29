"""Consistent SQLite backups and offline restores. Never overwrite a file.

python -m app.project_backup backup SOURCE DESTINATION
python -m app.project_backup restore SOURCE NEW_DESTINATION --stopped
"""

import argparse
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from app.services.backup_status import record_attempt


def validate(connection):
    if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity check failed')
    for query in (
        'SELECT id, title, completed, created_at FROM tasks LIMIT 1',
        'SELECT id, title, description, phase, position FROM roadmap LIMIT 1',
        'SELECT key, value FROM metadata LIMIT 1',
    ):
        connection.execute(query)


def copy_database(source: Path, destination: Path):
    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Destination already exists; choose a new filename')
    # No source creation and no modifications to the active database.
    reader = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=2)
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.project-backup-', dir=destination.parent)
        os.close(fd)
        temporary = Path(name)
        deadline = time.monotonic() + 30

        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('Backup could not finish within 30 seconds')

        writer = sqlite3.connect(temporary)
        try:
            reader.backup(writer, pages=128, progress=progress, sleep=0.05)
            validate(writer)
        finally:
            writer.close()
        with temporary.open('rb') as handle:
            os.fsync(handle.fileno())
        # Atomic publication with no overwrite even if another writer raced us.
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return destination
    finally:
        reader.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'restore'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--stopped', action='store_true', help='Confirm all API writers are stopped before restoring')
    args = parser.parse_args()
    if args.operation == 'restore' and not args.stopped:
        parser.error('Stop all API processes, then pass --stopped; restore only to a new path')
    try:
        destination = copy_database(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError, TimeoutError) as exc:
        if args.operation == 'backup':
            try:
                record_attempt(args.destination.absolute().parent / 'latest-backup.json')
            except (OSError, ValueError):
                pass
        parser.exit(1, f'{args.operation} failed: {exc}\n')
    print(destination)
    if args.operation == 'backup':
        try:
            record_attempt(destination.parent / 'latest-backup.json', destination)
        except (OSError, ValueError) as exc:
            parser.exit(1, f'Backup created, but status publication failed: {exc}\n')


if __name__ == '__main__':
    main()
