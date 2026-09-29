import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.system import MetricsUnavailable, SystemMonitor, collect_system, read_system


def test_cached_requests_do_not_sample_cpu(monkeypatch):
    sample = collect_system()
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'host')
    app.state.system_monitor = SimpleNamespace(snapshot=sample)
    def forbidden(*args, **kwargs):
        raise AssertionError('Requests must not sample CPU')
    monkeypatch.setattr('app.services.system.psutil.cpu_percent', forbidden)
    client = TestClient(app)
    for _ in range(20):
        response = client.get('/api/system')
        assert response.status_code == 200
        assert response.json()['sampled_at'] == sample.sampled_at.isoformat().replace('+00:00', 'Z')


def test_system_cache_expiry(monkeypatch):
    monkeypatch.setenv('DASHBOARD_METRICS_MODE', 'host')
    sample = collect_system()
    sample.sampled_at = datetime.now(timezone.utc) - timedelta(seconds=31)
    with pytest.raises(MetricsUnavailable):
        read_system(sample)
    with pytest.raises(MetricsUnavailable):
        read_system(None)


def test_background_sampling_populates_cache():
    monitor = SystemMonitor()
    asyncio.run(monitor.sample())
    assert monitor.snapshot is not None
