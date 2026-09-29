"""A bounded edit log, committed atomically with Project mutations.

No user identity is claimed before authentication exists. Not a tamper-proof log.
"""
from datetime import datetime, timezone


def initialize(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS project_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL)')


def record(connection, subject, detail):
    connection.execute('INSERT INTO project_audit (at, subject, detail) VALUES (?, ?, ?)',
                       (datetime.now(timezone.utc).isoformat(), subject, detail[:260]))
    connection.execute('DELETE FROM project_audit WHERE id NOT IN (SELECT id FROM project_audit ORDER BY id DESC LIMIT 500)')


def list_events():
    from app.services.tasks import database
    with database() as connection:
        return [{**dict(row), 'severity': 'info'} for row in connection.execute('SELECT * FROM project_audit ORDER BY id')]
