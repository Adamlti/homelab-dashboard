import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.system import collect_system
from app.services.tasks import database_path, initialize
from app.services.roadmap import initialize as initialize_roadmap


@pytest.fixture
def ready_client(monkeypatch, tmp_path):
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'services': [], 'tasks': [], 'roadmap': []}))
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(catalog))
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    path = tmp_path / 'system.json'
    path.write_text(collect_system().model_dump_json())
    monkeypatch.setenv('DASHBOARD_SNAPSHOT_PATH', str(path))
    initialize()
    initialize_roadmap()
    monkeypatch.setattr(app.state, 'health_monitor', SimpleNamespace(read=lambda: {'services': []}), raising=False)
    return TestClient(app), path


def test_ready_does_not_persist_probe(ready_client):
    client, _ = ready_client
    assert client.get('/api/ready').status_code == 200
    with sqlite3.connect(database_path()) as db:
        assert not db.execute("SELECT 1 FROM metadata WHERE key='readiness_probe'").fetchone()


@pytest.mark.parametrize('fault', ['missing', 'corrupt', 'locked', 'schema'])
def test_storage_failures_are_unhealthy(ready_client, fault):
    client, _ = ready_client
    db = None
    if fault == 'missing':
        database_path().unlink()
    elif fault == 'corrupt':
        database_path().write_text('not a database')
    elif fault == 'schema':
        with sqlite3.connect(database_path()) as connection:
            connection.execute('DROP TABLE roadmap')
    else:
        db = sqlite3.connect(database_path())
        db.execute('BEGIN IMMEDIATE')
    try:
        response = client.get('/api/ready')
        assert response.status_code == 503
        assert response.json()['dependencies']['sqlite']['status'] == 'unhealthy'
        assert client.get('/api/health').status_code == 200
    finally:
        if db:
            db.close()
    if fault == 'missing':
        assert not database_path().exists()


def test_stale_collector_and_config_mismatch_unhealthy(ready_client, monkeypatch):
    client, path = ready_client
    data = json.loads(path.read_text())
    data['sampled_at'] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    path.write_text(json.dumps(data))
    monkeypatch.setattr(app.state, 'health_monitor', SimpleNamespace(read=lambda: {'services': [{'status': 'unknown'}]}))
    response = client.get('/api/ready')
    assert response.status_code == 503
    assert response.json()['dependencies']['system']['status'] == 'unhealthy'
    assert response.json()['dependencies']['service_checks']['status'] == 'unhealthy'


def test_observed_service_outage_is_ready(ready_client, monkeypatch):
    client, _ = ready_client
    monkeypatch.setattr(app.state, 'health_monitor', SimpleNamespace(read=lambda: {'services': [{'status': 'offline'}]}))
    assert client.get('/api/ready').status_code == 200
