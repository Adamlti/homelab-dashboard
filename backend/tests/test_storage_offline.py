"""Storage/readiness regressions runnable without sockets or a server."""

import sqlite3
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.tasks import TaskUpdate
from app.project_backup import copy_database
from app.services import tasks, roadmap
from app.services.readiness import readiness, storage_ready
from app.services.system import MetricsUnavailable


@pytest.fixture
def store():
    tasks.initialize()
    roadmap.initialize()
    return tasks.database_path()


def test_backup_restore_roundtrip_and_no_overwrite(store, tmp_path):
    task = tasks.add_task('Backup regression')
    tasks.update_task(task['id'], {'completed': True, 'title': 'Renamed'})
    item = roadmap.add_item({'title': 'Recovery', 'phase': 'Next', 'description': 'Restore drill'})
    before_tasks, before_roadmap = tasks.list_tasks(), roadmap.list_items()
    backup = copy_database(store, tmp_path / 'backup.sqlite3')
    tasks.remove_task(task['id'])
    roadmap.remove_item(item['id'])
    restored = copy_database(backup, tmp_path / 'restored.sqlite3')
    with sqlite3.connect(restored) as db:
        db.row_factory = sqlite3.Row
        assert [dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY created_at, id')] == before_tasks
        assert [dict(r) for r in db.execute('SELECT * FROM roadmap ORDER BY position, id')] == before_roadmap
    with pytest.raises(FileExistsError):
        copy_database(store, backup)
    assert backup.stat().st_mode & 0o777 == 0o600


def test_backup_rejects_invalid_database_without_publishing(tmp_path):
    source = tmp_path / 'bad.sqlite3'
    source.write_text('broken')
    target = tmp_path / 'backup.sqlite3'
    with pytest.raises(sqlite3.Error):
        copy_database(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob('.project-backup-*'))


def test_readiness_checks_write_lock_and_schema(store):
    storage_ready()
    with sqlite3.connect(store) as connection:
        assert not connection.execute("SELECT 1 FROM metadata WHERE key='readiness_probe'").fetchone()
        connection.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError):
            storage_ready()
        connection.rollback()
        connection.execute('DROP TABLE roadmap')
    with pytest.raises(sqlite3.OperationalError):
        storage_ready()


def test_missing_storage_not_recreated(store):
    store.unlink()
    with pytest.raises(sqlite3.OperationalError):
        storage_ready()
    assert not store.exists()


def test_dependencies_report_stale_data_and_observed_outage(store, monkeypatch):
    monkeypatch.setattr('app.services.readiness.read_system', lambda _: object())
    state = SimpleNamespace(health_monitor=SimpleNamespace(read=lambda: {'services': [{'status': 'offline'}]}))
    assert readiness(state)['status'] == 'ready'
    def stale(_):
        raise MetricsUnavailable('stale')
    monkeypatch.setattr('app.services.readiness.read_system', stale)
    state.health_monitor.read = lambda: {'services': [{'status': 'stale'}]}
    result = readiness(state)
    assert result['status'] == 'not_ready'
    assert result['dependencies']['system']['status'] == 'unhealthy'
    assert result['dependencies']['service_checks']['status'] == 'unhealthy'


def test_partial_task_edit_and_validation(store):
    task = tasks.add_task('Original')
    tasks.update_task(task['id'], {'completed': True})
    updated = tasks.update_task(task['id'], TaskUpdate(title=' Renamed ').model_dump(exclude_unset=True))
    assert updated['title'] == 'Renamed' and updated['completed']
    for body in ({}, {'title': None}, {'completed': None}, {'completed': 'false'}, {'title': ' '}, {'title': 'x' * 201}):
        with pytest.raises(ValidationError):
            TaskUpdate.model_validate(body)


def test_read_only_database_is_unhealthy(store):
    store.chmod(0o400)
    try:
        with pytest.raises(sqlite3.OperationalError):
            storage_ready()
    finally:
        store.chmod(0o600)
