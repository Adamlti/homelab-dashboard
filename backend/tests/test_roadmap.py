import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.roadmap import initialize

HEADERS = {'X-Dashboard-Request': 'tasks', 'Content-Type': 'application/json'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'services': [], 'tasks': ['Preserve this task'], 'roadmap': [
        {'title': title, 'description': 'Details', 'phase': 'Next'} for title in ['First', 'Second', 'Third']
    ]}))
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(catalog))
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    with TestClient(app) as instance:
        yield instance


def test_add_edit_reorder_and_restart(client):
    original = client.get('/api/roadmap').json()
    added = client.post('/api/roadmap', headers=HEADERS, json={'title': 'Fourth', 'description': '', 'phase': 'Later'})
    assert added.status_code == 201
    row = added.json()
    edited = client.patch('/api/roadmap/' + row['id'], headers=HEADERS, json={'title': 'Updated', 'description': 'New notes', 'phase': 'Now'})
    assert edited.json()['title'] == 'Updated'
    order = [row['id'], *[item['id'] for item in original]]
    response = client.put('/api/roadmap/order', headers=HEADERS, json={'ids': order})
    assert response.status_code == 200
    assert [item['id'] for item in response.json()] == order
    initialize()
    with TestClient(app) as restarted:
        saved = restarted.get('/api/roadmap').json()
        assert [item['id'] for item in saved] == order
        assert [item['position'] for item in saved] == list(range(4))
        assert saved[0]['description'] == 'New notes'
        assert len(restarted.get('/api/tasks').json()) == 1


def test_deletions_persist_without_reseeding(client):
    tasks = client.get('/api/tasks').json()
    assert client.delete('/api/tasks/' + tasks[0]['id'], headers=HEADERS).status_code == 200
    rows = client.get('/api/roadmap').json()
    assert client.delete('/api/roadmap/' + rows[0]['id'], headers=HEADERS).status_code == 200
    with TestClient(app) as restarted:
        assert restarted.get('/api/tasks').json() == []
        assert len(restarted.get('/api/roadmap').json()) == 2
    assert client.delete('/api/tasks/' + tasks[0]['id'], headers=HEADERS).status_code == 404


def test_order_must_match_current_entries(client):
    ids = [item['id'] for item in client.get('/api/roadmap').json()]
    assert client.put('/api/roadmap/order', headers=HEADERS, json={'ids': ids[:-1]}).status_code == 409
    assert client.put('/api/roadmap/order', headers=HEADERS, json={'ids': ids + [str(uuid4())]}).status_code == 409
    assert client.put('/api/roadmap/order', headers=HEADERS, json={'ids': [ids[0]] * 3}).status_code == 422
    assert [item['id'] for item in client.get('/api/roadmap').json()] == ids


def test_stale_order_after_add_does_not_lose_item(client):
    ids = [item['id'] for item in client.get('/api/roadmap').json()]
    client.post('/api/roadmap', headers=HEADERS, json={'title': 'Concurrent addition', 'description': '', 'phase': 'Next'})
    assert client.put('/api/roadmap/order', headers=HEADERS, json={'ids': list(reversed(ids))}).status_code == 409
    assert len(client.get('/api/roadmap').json()) == 4


def test_roadmap_mutations_validate_input_and_origin(client):
    row = client.get('/api/roadmap').json()[0]
    assert client.delete('/api/roadmap/' + row['id']).status_code == 403
    assert client.delete('/api/tasks/' + str(uuid4())).status_code == 403
    assert client.put('/api/roadmap/order', headers={**HEADERS, 'Origin': 'https://other.example'}, json={'ids': []}).status_code == 403
    assert client.post('/api/roadmap', headers=HEADERS, json={'title': ' ', 'description': '', 'phase': 'Next'}).status_code == 422
    assert client.patch('/api/roadmap/' + str(uuid4()), headers=HEADERS, json={'title': 'Title', 'description': '', 'phase': 'Next'}).status_code == 404
