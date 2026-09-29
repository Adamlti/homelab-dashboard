import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import tasks

HEADERS = {'X-Dashboard-Request': 'tasks'}


@pytest.fixture
def task_client(tmp_path, monkeypatch):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'services': [], 'roadmap': [], 'tasks': ['Initial task']}))
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(path))
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    with TestClient(app) as client:
        yield client


def test_add_complete_and_restart_persistence(task_client):
    initial = task_client.get('/api/tasks').json()
    assert [task['title'] for task in initial] == ['Initial task']
    response = task_client.post('/api/tasks', json={'title': '  Back up media  '}, headers=HEADERS)
    assert response.status_code == 201
    task = response.json()
    assert task['title'] == 'Back up media'
    assert task['completed'] is False
    assert task_client.patch('/api/tasks/' + task['id'], json={'completed': True}, headers=HEADERS).json()['completed'] is True
    # A new store initialization must not overwrite tasks or repeat migration.
    tasks.initialize()
    assert len(tasks.list_tasks()) == 2
    with TestClient(app) as restarted:
        saved = restarted.get('/api/tasks').json()
        assert len(saved) == 2
        assert next(row for row in saved if row['id'] == task['id'])['completed'] is True
        assert restarted.patch('/api/tasks/' + task['id'], json={'completed': False}, headers=HEADERS).json()['completed'] is False


@pytest.mark.parametrize('body', [{'title': ''}, {'title': ' '}, {'title': 'x' * 201}, {'title': []}, {'title': 'ok', 'command': 'id'}])
def test_invalid_tasks_rejected(task_client, body):
    assert task_client.post('/api/tasks', json=body, headers=HEADERS).status_code == 422


def test_write_request_protection(task_client):
    assert task_client.post('/api/tasks', json={'title': 'bad'}).status_code == 403
    assert task_client.post('/api/tasks', json={'title': 'bad'}, headers={**HEADERS, 'Origin': 'https://other.example'}).status_code == 403
    assert task_client.post('/api/tasks', content='text', headers={**HEADERS, 'Content-Type': 'text/plain'}).status_code == 415
    assert task_client.delete('/api/tasks').status_code == 405
    assert task_client.patch('/api/tasks/' + str(uuid4()), json={'completed': True}, headers=HEADERS).status_code == 404
    task_id = task_client.get('/api/tasks').json()[0]['id']
    assert task_client.patch('/api/tasks/' + task_id, json={'completed': 'false'}, headers=HEADERS).status_code == 422


def test_concurrent_adds_are_not_lost(task_client):
    with ThreadPoolExecutor(max_workers=10) as pool:
        created = list(pool.map(tasks.add_task, [f'Task {i}' for i in range(30)]))
    assert len({task['id'] for task in created}) == 30
    assert len(tasks.list_tasks()) == 31


@pytest.mark.parametrize('change', [
    {'roadmap': None}, {'tasks': None}, {'roadmap': {}}, {'tasks': {}},
    {'tasks': [{}]}, {'tasks': [' ']}, {'roadmap': [{'title': 'bad'}]},
])
def test_invalid_catalog_project_fields_return_503(task_client, monkeypatch, change, eventually_get):
    from pathlib import Path
    import os
    path = Path(os.environ['DASHBOARD_CATALOG_PATH'])
    catalog = json.loads(path.read_text())
    catalog.update(change)
    path.write_text(json.dumps(catalog))
    eventually_get(task_client, '/api/catalog', 503)
    # Stored tasks remain accessible independently of catalog edits.
    assert task_client.get('/api/tasks').status_code == 200


@pytest.mark.parametrize('field', ['tasks', 'roadmap'])
def test_missing_catalog_project_fields_return_503(task_client, field, eventually_get):
    from pathlib import Path
    import os
    path = Path(os.environ['DASHBOARD_CATALOG_PATH'])
    catalog = json.loads(path.read_text())
    del catalog[field]
    path.write_text(json.dumps(catalog))
    eventually_get(task_client, '/api/catalog', 503)


def test_edit_title_preserves_completion(task_client):
    item = task_client.get('/api/tasks').json()[0]
    path = '/api/tasks/' + item['id']
    task_client.patch(path, json={'completed': True}, headers=HEADERS)
    response = task_client.patch(path, json={'title': '  Renamed  '}, headers=HEADERS)
    assert response.json()['title'] == 'Renamed'
    assert response.json()['completed'] is True
    for body in ({}, {'title': None}, {'completed': None}, {'title': ' '}, {'title': 'x' * 201}):
        assert task_client.patch(path, json=body, headers=HEADERS).status_code == 422
