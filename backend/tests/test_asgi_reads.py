"""Read-route integration via ASGI, without network sockets or a portal thread.

These exercise middleware and async read routes. They do not substitute for
threaded Project routes, actual HTTP listeners, Nginx or container tests.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.main import app
from app.models.system import SystemSnapshot
from app.models.health import HealthSnapshot, ProbeResult, ServiceConfig, config_hash
from app.services.health import HealthMonitor


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    system = SystemSnapshot(hostname='fixture-host', os='Ubuntu fixture', kernel='fixture', sampled_at=now,
                            uptime_seconds=123, cpu_percent=10, cpu_count=2,
                            memory={'total': 1000, 'used': 400, 'available': 600, 'percent': 40},
                            load_average=[0, 0, 0], disks=[], network=[])
    config = ServiceConfig(id='ssh', name='SSH', description='Fixture service', check={'type': 'tcp', 'host': '127.0.0.1', 'port': 22})
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'services': [config.model_dump(mode='json')], 'tasks': [], 'roadmap': []}))
    system_path = tmp_path / 'system.json'
    system_path.write_text(system.model_dump_json())
    services_path = tmp_path / 'services.json'
    services = HealthSnapshot(config_hash=config_hash([config]), services=[ProbeResult(id='ssh', status='online', detail='fixture', checked_at=now, last_success_at=now)])
    services_path.write_text(services.model_dump_json())
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(catalog))
    monkeypatch.setenv('DASHBOARD_SNAPSHOT_PATH', str(system_path))
    monkeypatch.setenv('DASHBOARD_SERVICES_SNAPSHOT_PATH', str(services_path))
    monkeypatch.setattr(app.state, 'health_monitor', HealthMonitor(), raising=False)
    return SimpleNamespace(system=system, system_path=system_path, services=services, services_path=services_path, catalog=catalog)


def request(path, method='GET'):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            return await client.request(method, path)
    return asyncio.run(run())


def test_async_reads_and_middleware(snapshots):
    for path in ('/', '/api/health', '/api/catalog', '/api/system', '/api/services'):
        response = request(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
    assert request('/api/system').json()['hostname'] == 'fixture-host'
    service = request('/api/services').json()['services'][0]
    assert service['status'] == 'online' and service['last_success_at'] and service['age_seconds'] >= 0


def test_stale_collector_http_contract(snapshots):
    snapshots.system.sampled_at -= timedelta(seconds=60)
    snapshots.system_path.write_text(snapshots.system.model_dump_json())
    snapshots.services.services[0].checked_at -= timedelta(seconds=60)
    snapshots.services_path.write_text(snapshots.services.model_dump_json())
    assert request('/api/system').status_code == 503
    assert request('/api/services').json()['services'][0]['status'] == 'stale'
    assert request('/api/health').status_code == 200


def test_invalid_catalog_and_config_mismatch(snapshots):
    catalog = json.loads(snapshots.catalog.read_text())
    catalog['services'][0]['check']['port'] = 2222
    snapshots.catalog.write_text(json.dumps(catalog))
    assert request('/api/services').json()['services'][0]['status'] == 'unknown'
    del catalog['roadmap']
    snapshots.catalog.write_text(json.dumps(catalog))
    assert request('/api/catalog').status_code == 503
    assert request('/api/services').status_code == 503


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_all_monitoring_routes_reject_writes(method):
    for path in ('/api/health', '/api/ready', '/api/system', '/api/services', '/api/catalog', '/api/history', '/api/backups'):
        assert request(path, method).status_code == 405
