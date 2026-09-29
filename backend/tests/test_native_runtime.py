import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.frontend import app as frontend
from app.services.health import HealthMonitor
from app.services.publisher import publisher_lock
from app.services.logs.samba import file_entries
from app.services.logs.general import human_message


def test_publishers_are_exclusive_and_release():
    with publisher_lock():
        with pytest.raises(RuntimeError, match='Another host publisher'):
            with publisher_lock():
                pass
    with publisher_lock():
        pass


def test_health_monitor_reuses_and_closes_client(monkeypatch):
    clients, seen, closed = [], [], []
    @asynccontextmanager
    async def client():
        value = object()
        clients.append(value)
        try:
            yield value
        finally:
            closed.append(value)
    async def collect(**kwargs):
        seen.append(kwargs['client'])
        if len(seen) == 10:
            raise asyncio.CancelledError()
        return SimpleNamespace()
    async def pause(_):
        pass
    monkeypatch.setattr('app.services.health.health_client', client)
    monkeypatch.setattr('app.services.health.collect_health', collect)
    monkeypatch.setattr('app.services.health.asyncio.sleep', pause)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(HealthMonitor().run())
    assert len(clients) == 1 and seen == clients * 10 and closed == clients


def test_proxy_preserves_host_origin_and_security_headers():
    requests = []
    def upstream(request):
        requests.append(request)
        return httpx.Response(201, json={'id': 'fixture'})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream), base_url='http://127.0.0.1:8008') as client:
            frontend.state.client = client
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=frontend), base_url='http://dashboard.local:5173') as browser:
                response = await browser.post('/api/tasks', headers={'Origin': 'http://dashboard.local:5173', 'X-Dashboard-Request': 'tasks'}, json={'title': 'fixture'})
                assert response.status_code == 201
                assert response.headers['x-frame-options'] == 'DENY'
                assert "script-src 'self'" in response.headers['content-security-policy']
                assert 'access-control-allow-origin' not in response.headers
                assert (await browser.post('/api/system')).status_code == 405
                assert (await browser.post('/api/tasks', content=b'x' * 65537)).status_code == 413
    asyncio.run(exercise())
    assert len(requests) == 1
    assert requests[0].headers['host'] == 'dashboard.local:5173'
    assert requests[0].headers['origin'] == 'http://dashboard.local:5173'
    assert requests[0].url.host == '127.0.0.1'


def test_samba_oversized_records_split_redacted_with_original_timestamp(tmp_path):
    log = tmp_path / 'smbd'
    log.write_text('[2026/09/27 05:00:00.123456, 0] source\n' + '\n'.join(
        f'  warning {index}: password=hidden ' + 'context ' * 12 for index in range(30)))
    rows, _ = file_entries(log)
    assert len(rows) == 31
    assert len({row.timestamp for row in rows}) == 1
    assert all(len(row.message) <= 1200 and 'hidden' not in row.message for row in rows)
    assert sum(row.severity == 'warning' for row in rows) == 30


def test_samba_split_does_not_expose_private_key_continuations(tmp_path):
    log = tmp_path / 'smbd'
    log.write_text('[2026/09/27 05:00:00.123456, 0] source\n-----BEGIN PRIVATE KEY-----\n' + 'sensitive' * 500)
    rows, _ = file_entries(log)
    assert len(rows) == 1 and rows[0].message == '[Sensitive private key material redacted]'


def test_alert_history_names_service_and_does_not_invent_recovery():
    assert human_message('jellyfin', 'Changed: Service check: offline', {'jellyfin': 'Jellyfin'}) == 'Jellyfin is unavailable. Alert changed.'
    assert 'unconfirmed' in human_message('jellyfin', 'Observation lost: Service check: offline', {'jellyfin': 'Jellyfin'})


def test_history_cache_does_not_freeze_freshness_or_share_mutation(tmp_path):
    from datetime import datetime, timezone, timedelta
    from app.collector import write_json
    from app.services.telemetry import TelemetrySnapshot, read_telemetry, load_history, validated_history
    path = tmp_path / 'history.json'
    now = datetime.now(timezone.utc)
    write_json(path, TelemetrySnapshot(sampled_at=now))
    assert not read_telemetry(path, now)['stale']
    assert read_telemetry(path, now + timedelta(seconds=31))['stale']
    loaded = load_history(path)
    loaded.sampled_at = now - timedelta(days=1)
    assert load_history(path).sampled_at == now
    write_json(path, TelemetrySnapshot(sampled_at=now + timedelta(seconds=5)))
    assert load_history(path).sampled_at == now + timedelta(seconds=5)
    assert validated_history.cache_info().currsize == 1


def test_samba_summarizes_repeated_warnings_even_on_one_physical_line(tmp_path):
    log = tmp_path / 'smbd'
    warning = 'WARNING: Unhandled message: path=/org/freedesktop/DBus token=hidden '
    log.write_text('[2026/09/27 05:00:00.123456, 0] startup ' + warning * 50)
    rows, _ = file_entries(log)
    assert len(rows) == 2
    assert rows[1].message.startswith('Repeated 50 times in this file record: WARNING:')
    assert '[REDACTED]' in rows[1].message and 'hidden' not in rows[1].message
    assert len(rows[1].message) < 200 and rows[1].severity == 'warning'


def test_samba_labels_shortening_of_one_large_nonrepeating_line(tmp_path):
    log = tmp_path / 'smbd'
    log.write_text('[2026/09/27 05:00:00.123456, 0] warning ' + 'context ' * 150)
    rows, _ = file_entries(log)
    assert len(rows) == 1 and len(rows[0].message) < 600
    assert 'more characters omitted' in rows[0].message
