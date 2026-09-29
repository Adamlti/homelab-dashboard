import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from app.collector import write_snapshot
from app.main import app
from app.services.system import collect_system

client = TestClient(app)


def test_health_and_root():
    assert client.get('/').status_code == 200
    health = client.get('/api/health')
    assert health.json()['host_read_only'] is True
    assert health.json()['writable_features'] == ['tasks', 'roadmap', 'notes']
    assert health.headers['cache-control'] == 'no-store'


def test_live_host_values(monkeypatch):
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'host')
    from types import SimpleNamespace
    app.state.system_monitor = SimpleNamespace(snapshot=collect_system())
    response = client.get('/api/system')
    assert response.status_code == 200
    data = response.json()
    assert data['hostname'] == socket.gethostname()
    assert data['memory']['total'] == psutil.virtual_memory().total
    assert data['disks'][0]['total'] == psutil.disk_usage('/').total
    assert len(data['load_average']) == 3
    assert data['uptime_seconds'] > 0


def test_collector_publishes_valid_snapshot(tmp_path, monkeypatch):
    path = tmp_path / 'system.json'
    write_snapshot(path)
    assert not path.with_suffix('.tmp').exists()
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    monkeypatch.setenv('DASHBOARD_SNAPSHOT_PATH', str(path))
    response = client.get('/api/system')
    assert response.status_code == 200
    assert response.json()['source'] == 'collector'
    assert response.json()['hostname'] == socket.gethostname()


@pytest.mark.parametrize('condition', ['missing', 'invalid', 'old', 'future', 'naive', 'oversize'])
def test_bad_snapshots_never_fall_back_to_container_metrics(condition, tmp_path, monkeypatch):
    path = tmp_path / 'system.json'
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    monkeypatch.setenv('DASHBOARD_SNAPSHOT_PATH', str(path))
    if condition == 'invalid':
        path.write_text('{bad json')
    elif condition == 'oversize':
        path.write_text('x' * 1_048_577)
    elif condition != 'missing':
        data = collect_system().model_dump(mode='json')
        stamp = datetime.now(timezone.utc) + timedelta(seconds=-60 if condition == 'old' else 60)
        if condition == 'naive':
            stamp = stamp.replace(tzinfo=None)
        data['sampled_at'] = stamp.isoformat()
        path.write_text(json.dumps(data))
    assert client.get('/api/system').status_code == 503
    assert client.get('/api/health').status_code == 200


def test_container_cannot_report_its_own_metrics_as_host(monkeypatch):
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'host')
    original = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda self: True if str(self) == '/.dockerenv' else original(self))
    assert client.get('/api/system').status_code == 503


def test_catalog_exposes_explicit_probe_configuration():
    response = client.get('/api/catalog')
    assert response.status_code == 200
    services = response.json()['services']
    assert len(services) == 6
    assert sum(service['check'] is not None for service in services) == 5
    assert next(service for service in services if service['id'] == 'docker')['check'] is None


def test_missing_catalog_has_controlled_error(monkeypatch):
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', '/nonexistent-dashboard-catalog.json')
    assert client.get('/api/catalog').status_code == 503


@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_monitoring_endpoints_reject_writes(method):
    for path in ['/api/system', '/api/health', '/api/catalog', '/api/services', '/api/ready', '/api/history', '/api/backups',
                 '/api/logs/general', '/api/logs/server', '/api/logs/samba']:
        assert getattr(client, method)(path).status_code == 405
    assert getattr(client, method)('/api/exec').status_code == 404
