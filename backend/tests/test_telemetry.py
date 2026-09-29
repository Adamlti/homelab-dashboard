from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.collector import write_json
from app.services.telemetry import Telemetry, read_telemetry, load_history


def system(now, cpu=10, memory=30, disk=40):
    return SimpleNamespace(sampled_at=now, cpu_percent=cpu, memory=SimpleNamespace(percent=memory),
                           disks=[SimpleNamespace(percent=disk)] if disk is not None else [])


def services(status):
    return {'services': [{'id': 'ssh', 'status': status}]}


def test_thresholds_transitions_and_recovery_without_duplicate_events(tmp_path):
    now = datetime.now(timezone.utc)
    history = Telemetry(tmp_path / 'history.json')
    first = history.observe(system(now), services('online'), now)
    count = len(first.events)
    unchanged = history.observe(system(now), services('online'), now + timedelta(seconds=10))
    assert len(unchanged.events) == count and len(unchanged.points) == 1
    later = now + timedelta(seconds=60)
    failed = history.observe(system(later, cpu=90, memory=90, disk=85), services('offline'), later)
    assert {alert.subject for alert in failed.alerts} == {'CPU', 'Memory', 'Storage', 'ssh'}
    assert any(event.detail == 'online → offline' for event in failed.events)
    recovery = history.observe(system(later), services('online'), later + timedelta(seconds=10))
    assert recovery.alerts == []
    assert any(event.detail == 'offline → online' for event in recovery.events)


def test_stale_metrics_never_become_new_points(tmp_path):
    now = datetime.now(timezone.utc)
    history = Telemetry(tmp_path / 'history.json')
    result = history.observe(system(now - timedelta(seconds=31)), None, now)
    assert not result.points
    assert {alert.subject for alert in result.alerts} == {'System', 'Services'}
    result = history.observe(system(now + timedelta(seconds=60)), None, now)
    assert not result.points


def test_retention_and_serialized_restart(tmp_path):
    now = datetime.now(timezone.utc) - timedelta(hours=80)
    path = tmp_path / 'history.json'
    history = Telemetry(path)
    for index in range(4801):
        at = now + timedelta(minutes=index)
        history.observe(system(at), services('offline' if index % 2 else 'online'), at)
    assert len(history.snapshot.points) == 4320
    assert len(history.snapshot.events) == 100
    assert len(history.snapshot.alert_history) == 100
    assert history.snapshot.points[0].at >= at - timedelta(hours=72)
    write_json(path, history.snapshot)
    restarted = Telemetry(path)
    result = restarted.observe(system(at), services('online'), at)
    assert result == history.snapshot
    assert path.stat().st_size < 1_048_576
    view = read_telemetry(path, now=at + timedelta(seconds=31))
    assert view['stale'] is True and 'states' not in view


def test_missing_corrupt_oversize_and_absent_disks(tmp_path):
    path = tmp_path / 'history.json'
    with pytest.raises(OSError):
        read_telemetry(path)
    for content in ('invalid', 'x' * 1_048_577):
        path.write_text(content)
        with pytest.raises(ValueError):
            load_history(path)
        assert Telemetry(path).snapshot.points == []
    now = datetime.now(timezone.utc)
    result = Telemetry(path).observe(system(now, disk=None), services('not_configured'), now)
    assert result.points[0].disk is None and not result.alerts


def test_reader_expires_history_when_collector_stops(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / 'history.json'
    history = Telemetry(path)
    write_json(path, history.observe(system(now), services('online'), now))
    view = read_telemetry(path, now + timedelta(hours=73))
    assert view['stale'] and view['points'] == [] and view['events'] == []


def test_alert_history_records_raise_recovery_and_restart(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / 'history.json'
    history = Telemetry(path)
    history.observe(system(now, cpu=95), services('offline'), now)
    assert len(history.snapshot.alert_history) == 2
    # Numeric movement within the same threshold is not a new alert.
    history.observe(system(now, cpu=96), services('offline'), now + timedelta(seconds=10))
    assert len(history.snapshot.alert_history) == 2
    write_json(path, history.snapshot)
    history = Telemetry(path)
    result = history.observe(system(now), services('online'), now + timedelta(seconds=20))
    assert [event.detail.split(':')[0] for event in result.alert_history] == ['Raised', 'Raised', 'Cleared', 'Cleared']
    assert not result.alerts
    write_json(path, result)
    assert len(read_telemetry(path, now + timedelta(seconds=21))['alert_history']) == 4
    assert read_telemetry(path, now + timedelta(hours=73))['alert_history'] == []


def test_alert_observation_loss_is_not_a_recovery(tmp_path):
    now = datetime.now(timezone.utc)
    history = Telemetry(tmp_path / 'history.json')
    history.observe(system(now, cpu=95), services('offline'), now)
    result = history.observe(None, None, now + timedelta(seconds=10))
    lost = [event for event in result.alert_history if event.subject in ('CPU', 'ssh') and event.at > now]
    assert len(lost) == 2 and all(event.detail.startswith('Observation lost:') for event in lost)


def test_old_snapshots_load_without_alert_history(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / 'history.json'
    history = Telemetry(path)
    data = history.observe(system(now), services('online'), now).model_dump_json(exclude={'alert_history'})
    path.write_text(data)
    assert read_telemetry(path, now)['alert_history'] == []


def test_disabling_a_service_check_does_not_claim_recovery(tmp_path):
    now = datetime.now(timezone.utc)
    history = Telemetry(tmp_path / 'history.json')
    history.observe(system(now), services('offline'), now)
    result = history.observe(system(now), services('not_configured'), now + timedelta(seconds=10))
    assert result.alert_history[-1].detail.startswith('Observation lost:')


def test_operator_thresholds_and_startup_labels(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_ALERT_CPU', '50')
    now = datetime.now(timezone.utc)
    history = Telemetry(tmp_path / 'history.json')
    result = history.observe(system(now, cpu=55), services('unknown'), now)
    assert any(a.subject == 'CPU' for a in result.alerts)
    assert any(e.subject == 'service:ssh' and e.detail.startswith('Startup:') for e in result.events)
    for invalid in ('nan', 'inf', '0', '101'):
        monkeypatch.setenv('DASHBOARD_ALERT_CPU', invalid)
        with pytest.raises(ValueError):
            Telemetry(tmp_path / 'other.json')
