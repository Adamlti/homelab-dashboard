"""Only dashboard task data is writable. SQLite transactions serialize mutations."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.services.catalog import read_catalog
from app.services import audit


def database_path():
    return Path(os.getenv('DASHBOARD_TASKS_PATH', str(
        Path(__file__).resolve().parents[3] / 'data/tasks/tasks.sqlite3')))


@contextmanager
def database():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize():
    with database() as connection, connection:
        audit.initialize(connection)
        connection.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute("SELECT 1 FROM metadata WHERE key='catalog_imported'").fetchone():
            return
        # If catalog is invalid, leave migration pending until the operator fixes it.
        try:
            seeds = read_catalog()['tasks']
        except (OSError, ValueError):
            return
        for title in seeds:
            connection.execute('INSERT INTO tasks VALUES (?, ?, 0, ?)',
                               (str(uuid4()), title, datetime.now(timezone.utc).isoformat()))
        connection.execute("INSERT INTO metadata VALUES ('catalog_imported', '1')")


def list_tasks():
    with database() as connection:
        return [dict(row) for row in connection.execute('SELECT * FROM tasks ORDER BY created_at, id')]


def add_task(title):
    with database() as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT count(*) FROM tasks').fetchone()[0] >= 1000:
            raise OverflowError('Task limit reached (1000)')
        task = {'id': str(uuid4()), 'title': title, 'completed': False,
                'created_at': datetime.now(timezone.utc).isoformat()}
        connection.execute('INSERT INTO tasks VALUES (:id, :title, :completed, :created_at)', task)
        audit.record(connection, 'Tasks', 'Added: ' + title)
        return task


def update_task(task_id, changes):
    with database() as connection, connection:
        # Field names are a fixed allowlist; values always use parameters.
        fields = [field for field in ('title', 'completed') if field in changes]
        result = connection.execute('UPDATE tasks SET ' + ', '.join(f'{field}=?' for field in fields) + ' WHERE id=?',
                                    [changes[field] for field in fields] + [str(task_id)])
        if result.rowcount == 0:
            raise LookupError('Task not found')
        row = dict(connection.execute('SELECT * FROM tasks WHERE id=?', (str(task_id),)).fetchone())
        audit.record(connection, 'Tasks', 'Updated ' + ', '.join(fields) + ': ' + row['title'])
        return row


def remove_task(task_id):
    with database() as connection, connection:
        if connection.execute('DELETE FROM tasks WHERE id=?', (str(task_id),)).rowcount == 0:
            raise LookupError('Task not found')
        audit.record(connection, 'Tasks', 'Removed task ' + str(task_id))
        return {'id': str(task_id)}
