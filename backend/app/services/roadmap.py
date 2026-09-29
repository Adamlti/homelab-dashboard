"""Persistent roadmap entries and transactional ordering in the project database."""
from uuid import uuid4

from app.services.tasks import database
from app.services.catalog import read_catalog
from app.services import audit


def initialize():
    with database() as connection, connection:
        connection.execute('CREATE TABLE IF NOT EXISTS roadmap (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, phase TEXT NOT NULL, position INTEGER NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute("SELECT 1 FROM metadata WHERE key='roadmap_imported'").fetchone():
            return
        try:
            seeds = read_catalog()['roadmap']
        except (OSError, ValueError):
            return
        for position, item in enumerate(seeds):
            connection.execute('INSERT INTO roadmap VALUES (?, ?, ?, ?, ?)',
                               (str(uuid4()), item['title'], item['description'], item['phase'], position))
        connection.execute("INSERT INTO metadata VALUES ('roadmap_imported', '1')")


def list_items():
    with database() as connection:
        return [dict(row) for row in connection.execute('SELECT * FROM roadmap ORDER BY position, id')]


def add_item(item):
    with database() as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT count(*) FROM roadmap').fetchone()[0] >= 100:
            raise OverflowError('Roadmap limit reached (100)')
        position = connection.execute('SELECT coalesce(max(position), -1) + 1 FROM roadmap').fetchone()[0]
        row = {**item, 'id': str(uuid4()), 'position': position}
        connection.execute('INSERT INTO roadmap VALUES (:id, :title, :description, :phase, :position)', row)
        audit.record(connection, 'Roadmap', 'Added: ' + row['title'])
        return row


def update_item(item_id, item):
    with database() as connection, connection:
        result = connection.execute('UPDATE roadmap SET title=:title, description=:description, phase=:phase WHERE id=:id', {**item, 'id': str(item_id)})
        if result.rowcount == 0:
            raise LookupError('Roadmap item not found')
        audit.record(connection, 'Roadmap', 'Updated: ' + item['title'])
        return dict(connection.execute('SELECT * FROM roadmap WHERE id=?', (str(item_id),)).fetchone())


def remove_item(item_id):
    with database() as connection, connection:
        if connection.execute('DELETE FROM roadmap WHERE id=?', (str(item_id),)).rowcount == 0:
            raise LookupError('Roadmap item not found')
        audit.record(connection, 'Roadmap', 'Removed item ' + str(item_id))
        return {'id': str(item_id)}


def reorder(ids):
    ids = [str(item_id) for item_id in ids]
    with database() as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        current = {row[0] for row in connection.execute('SELECT id FROM roadmap')}
        if len(ids) != len(current) or set(ids) != current:
            raise OverflowError('Roadmap changed. Refresh it and try again.')
        connection.executemany('UPDATE roadmap SET position=? WHERE id=?', enumerate(ids))
        audit.record(connection, 'Roadmap', f'Reordered {len(ids)} items')
        return [dict(row) for row in connection.execute('SELECT * FROM roadmap ORDER BY position, id')]
