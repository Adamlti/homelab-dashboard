import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import audit


@pytest.fixture
def task_client(tmp_path, monkeypatch):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'services': [], 'roadmap': [], 'tasks': ['Initial task']}))
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(path))
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    with TestClient(app) as client:
        yield client


def test_notes_are_persistent_and_audited(task_client):
    initial = task_client.get('/api/notes')
    assert initial.status_code == 200
    assert initial.json() == {'content': '', 'updated_at': None}

    response = task_client.patch('/api/notes', json={'content': 'Remember the restore drill.'}, headers={'X-Dashboard-Request': 'tasks'})
    assert response.status_code == 200
    assert response.json()['content'] == 'Remember the restore drill.'
    assert response.json()['updated_at']

    assert task_client.get('/api/notes').json() == response.json()
    assert any(row['subject'] == 'Notes' for row in audit.list_events())


def test_notes_validation_and_write_guard(task_client):
    assert task_client.patch('/api/notes', json={'content': 'x'}, headers={}).status_code == 403
    assert task_client.patch('/api/notes', json={'content': 'x', 'extra': 1}, headers={'X-Dashboard-Request': 'tasks'}).status_code == 422
    assert task_client.patch('/api/notes', json={'content': 'x' * 5001}, headers={'X-Dashboard-Request': 'tasks'}).status_code == 422
