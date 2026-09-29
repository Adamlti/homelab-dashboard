import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.collector import write_json
from app.main import app
from app.models.health import HealthSnapshot, HTTPProbe, ProbeResult, ServiceConfig, ServiceList, config_hash
from app.services.health import HealthMonitor, collect_health, health_view, probe


def service(check=None):
    return ServiceConfig(id='test', name='Test', description='Test service', check=check)


def http_service(port=80, **kwargs):
    return service({'type': 'http', 'url': f'http://127.0.0.1:{port}/health', **kwargs})


def snapshot(config, status='online', age=0):
    return HealthSnapshot(config_hash=config_hash([config]), services=[ProbeResult(
        id=config.id, status=status, detail='Test observation', latency_ms=1,
        checked_at=datetime.now(timezone.utc) - timedelta(seconds=age),
    )])


@pytest.mark.parametrize('code,expected', [(200, 'online'), (503, 'offline'), (302, 'offline'), (401, 'offline')])
def test_http_status_and_no_redirects(monkeypatch, code, expected):
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(code, headers={'location': 'http://8.8.8.8/blocked'})

    def client(**kwargs):
        assert kwargs['trust_env'] is False
        assert kwargs['follow_redirects'] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, 'AsyncClient', client)
    result = asyncio.run(probe(http_service()))
    assert result.status == expected
    assert result.http_status == code
    assert len(requests) == 1
    assert requests[0].method == 'GET'
    assert result.checked_at.tzinfo is not None
    assert result.latency_ms >= 0


def test_explicit_expected_redirect(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        **kw, transport=httpx.MockTransport(lambda req: httpx.Response(302))))
    assert asyncio.run(probe(http_service(expected_statuses=[200, 302]))).status == 'online'


def test_http_deadline_against_slow_local_server():
    async def run():
        async def slow(reader, writer):
            try:
                await reader.read(1024)
                await asyncio.sleep(5)
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(slow, '127.0.0.1', 0)
        async with server:
            result = await probe(http_service(server.sockets[0].getsockname()[1], timeout_seconds=0.1))
        assert result.status == 'timeout'
        assert result.latency_ms < 1000
    asyncio.run(run())


def test_tcp_reachable_and_refused():
    async def run():
        async def accept(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(accept, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        config = service({'type': 'tcp', 'host': '127.0.0.1', 'port': port})
        async with server:
            assert (await probe(config)).status == 'online'
        result = await probe(config)
        assert result.status == 'offline'
        assert result.http_status is None
    asyncio.run(run())


def test_tcp_deadline(monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(5)
    monkeypatch.setattr(asyncio, 'open_connection', slow)
    result = asyncio.run(probe(service({'type': 'tcp', 'host': '127.0.0.1', 'port': 22, 'timeout_seconds': 0.1})))
    assert result.status == 'timeout'


def test_http_protocol_error(monkeypatch):
    original = httpx.AsyncClient
    def handler(request):
        raise httpx.RemoteProtocolError('private upstream detail')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    result = asyncio.run(probe(http_service()))
    assert result.status == 'error'
    assert 'private upstream' not in result.detail


@pytest.mark.parametrize('url', ['http://8.8.8.8/', 'http://169.254.169.254/', 'file:///etc/passwd',
    'http://example.com/', 'http://u:p@127.0.0.1/', 'http://127.0.0.1/?token=x', 'http://127.0.0.1/#x', 'http://127.0.0.1:0/'])
def test_disallowed_http_targets(url):
    with pytest.raises(ValidationError):
        HTTPProbe(type='http', url=url)


def test_configuration_limits():
    with pytest.raises(ValidationError):
        http_service(timeout_seconds=10)
    with pytest.raises(ValidationError):
        ServiceList(services=[service(), service()])
    with pytest.raises(ValidationError):
        service({'type': 'tcp', 'host': 'example.com', 'port': 22})
    with pytest.raises(ValidationError):
        http_service(expected_statuses=[999])


@pytest.mark.parametrize('age,status', [(0, 'online'), (31, 'stale'), (-10, 'stale')])
def test_freshness_preserves_last_observation(age, status):
    config = http_service()
    result = health_view(snapshot(config, age=age), [config])['services'][0]
    assert result['status'] == status
    assert result['last_status'] == ('online' if status == 'stale' else None)
    assert result['checked_at']


def test_changed_target_invalidates_old_result():
    old = http_service()
    changed = http_service(port=8096)
    row = health_view(snapshot(old), [changed])['services'][0]
    assert row['status'] == 'unknown'
    assert row['checked_at'] is None


def test_unconfigured_never_probed():
    result = asyncio.run(collect_health([service()]))
    assert result.services[0].status == 'not_configured'
    assert result.services[0].checked_at is None


@pytest.mark.parametrize('age,status', [(0, 'online'), (60, 'stale')])
def test_collector_endpoint_reads_fresh_or_stale_snapshot(tmp_path, monkeypatch, age, status, eventually_get):
    config = http_service()
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'services': [config.model_dump(mode='json')], 'roadmap': [], 'tasks': []}))
    output = tmp_path / 'services.json'
    write_json(output, snapshot(config, age=age))
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(catalog))
    monkeypatch.setenv('DASHBOARD_SERVICES_SNAPSHOT_PATH', str(output))
    with TestClient(app) as client:
        response = client.get('/api/services')
        assert response.status_code == 200
        assert response.json()['services'][0]['status'] == status
        assert client.get('/api/health').status_code == 200
        output.write_text('bad json')
        eventually_get(client, '/api/services', 503)
        output.unlink()
        eventually_get(client, '/api/services', 503)


def test_api_reads_cached_results_without_running_probes(monkeypatch):
    async def unexpected_probe():
        raise AssertionError('GET endpoint must not launch probes')
    config = http_service()
    monitor = HealthMonitor()
    monitor.snapshot = snapshot(config)
    monkeypatch.setattr('app.services.health.service_configs', lambda: [config])
    monkeypatch.setattr('app.services.health.collect_health', unexpected_probe)
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'host')
    app.state.health_monitor = monitor
    client = TestClient(app)
    assert client.get('/api/services').json()['services'][0]['status'] == 'online'


def test_invalid_catalog_is_controlled_for_both_endpoints(tmp_path, monkeypatch, eventually_get):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'services': [{'id': 'bad', 'name': 'Bad', 'description': '', 'check': {'type': 'shell'}}]}))
    monkeypatch.setenv('DASHBOARD_CATALOG_PATH', str(path))
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'collector')
    with TestClient(app) as client:
        assert client.get('/api/catalog').status_code == 503
        eventually_get(client, '/api/services', 503)


def test_last_success_survives_failures_but_not_configuration_changes():
    from app.services.health import retain_success
    config = http_service()
    previous = snapshot(config)
    stamp = previous.services[0].checked_at
    previous.services[0].last_success_at = stamp
    previous = HealthSnapshot.model_validate_json(previous.model_dump_json())
    failed = ProbeResult(id=config.id, status='offline', detail='refused', checked_at=datetime.now(timezone.utc))
    retain_success([failed], previous, [config])
    assert failed.last_success_at == stamp
    view = health_view(HealthSnapshot(config_hash=config_hash([config]), services=[failed]), [config])['services'][0]
    assert view['last_success_at'] and view['age_seconds'] >= 0
    changed = http_service(port=8096)
    other = failed.model_copy(update={'last_success_at': None})
    retain_success([other], previous, [changed])
    assert other.last_success_at is None
    success = failed.model_copy(update={'status': 'online', 'last_success_at': failed.checked_at})
    retain_success([success], previous, [config])
    assert success.last_success_at == failed.checked_at


@pytest.mark.parametrize('greeting,expected', [(b'SSH-2.0-Test\r\n', 'online'), (b'HTTP/1.1 200 OK\r\n', 'error'), (b'x' * 600 + b'\n', 'error')])
def test_ssh_adapter_checks_protocol_without_logging_in(greeting, expected):
    async def run():
        async def accept(reader, writer):
            writer.write(greeting)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(accept, '127.0.0.1', 0)
        config = service({'type': 'ssh', 'host': '127.0.0.1', 'port': server.sockets[0].getsockname()[1]})
        async with server:
            result = await probe(config)
        assert result.status == expected
        assert 'Test' not in result.detail
    asyncio.run(run())
