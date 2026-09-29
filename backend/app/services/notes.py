from datetime import datetime, timezone

from app.services import audit
from app.services.tasks import database


def read_notes():
    with database() as connection:
        content = connection.execute("SELECT value FROM metadata WHERE key='notes'").fetchone()
        updated = connection.execute("SELECT value FROM metadata WHERE key='notes_updated_at'").fetchone()
        return {'content': content['value'] if content else '', 'updated_at': updated['value'] if updated else None}


def update_notes(content):
    now = datetime.now(timezone.utc).isoformat()
    with database() as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("INSERT INTO metadata (key, value) VALUES ('notes', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (content,))
        connection.execute("INSERT INTO metadata (key, value) VALUES ('notes_updated_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now,))
        audit.record(connection, 'Notes', 'Updated notes to self')
        return {'content': content, 'updated_at': now}
