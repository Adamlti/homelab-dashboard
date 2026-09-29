import json
from types import SimpleNamespace

from app.services.response_cache import ResponseCache, Entry


def cache_state(monkeypatch):
    monkeypatch.setattr('app.services.response_cache.read_system', lambda _: SimpleNamespace(model_dump=lambda **_: {'hostname': 'fixture'}))
    monkeypatch.setattr('app.services.response_cache.read_catalog', lambda: {'services': []})
    monkeypatch.setattr('app.services.response_cache.read_telemetry', lambda: {'stale': False})
    monkeypatch.setattr('app.services.response_cache.read_backup_status', lambda: {'status': 'unknown'})
    monkeypatch.setattr('app.services.response_cache.readiness', lambda _: {'status': 'ready'})
    return SimpleNamespace(system_monitor=SimpleNamespace(snapshot=None), health_monitor=SimpleNamespace(read=lambda: {'services': []}))


def test_cache_reads_only_preencoded_bytes_and_expires(monkeypatch):
    cache = ResponseCache(cache_state(monkeypatch))
    cache.refresh()
    payload = cache.entries['/api/system'].body
    monkeypatch.setattr('app.services.response_cache.read_system', lambda _: (_ for _ in ()).throw(AssertionError('request read source')))
    for _ in range(100):
        assert cache.response('/api/system').body is payload
    entry = cache.entries['/api/system']
    cache.entries['/api/system'] = Entry(entry.body, entry.status, entry.built_at - 3)
    assert cache.response('/api/system').status_code == 503


def test_cache_does_not_hide_dependency_failures(monkeypatch):
    cache = ResponseCache(cache_state(monkeypatch))
    cache.refresh()
    monkeypatch.setattr('app.services.response_cache.readiness', lambda _: {'status': 'not_ready', 'dependencies': {'sqlite': {'status': 'unhealthy'}}})
    monkeypatch.setattr('app.services.response_cache.read_catalog', lambda: (_ for _ in ()).throw(ValueError('invalid catalog')))
    cache.refresh()
    assert cache.response('/api/ready').status_code == 503
    assert json.loads(cache.response('/api/ready').body)['dependencies']['sqlite']['status'] == 'unhealthy'
    assert cache.response('/api/catalog').status_code == 503


def test_unchanged_cache_reuses_bytes_and_keeps_bounded_state(monkeypatch):
    cache = ResponseCache(cache_state(monkeypatch))
    cache.refresh()
    original = cache.entries['/api/history'].body
    for _ in range(200):
        cache.refresh()
    assert cache.entries['/api/history'].body is original
    assert len(cache.entries) == len(cache.last_data) == 6
    assert cache.serializations == 6 and cache.reuses == 1200


def test_slow_dependencies_are_not_polled_every_cycle(monkeypatch):
    cache = ResponseCache(cache_state(monkeypatch))
    cache.refresh()
    monkeypatch.setattr('app.services.response_cache.readiness', lambda _: (_ for _ in ()).throw(AssertionError('excessive readiness IO')))
    cache.refresh(force=False)
    assert cache.response('/api/ready').status_code == 200
