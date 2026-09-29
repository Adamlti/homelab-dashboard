import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.logs import LogEntry
from app.services.logs import common, general, samba, server


def row(message, severity='info', source='smbd'):
    return LogEntry(timestamp=datetime.now(timezone.utc), message=message, severity=severity, source=source)


def test_startup_alerts_are_filtered_without_hiding_real_incidents(monkeypatch):
    details = ['Raised: Startup: Service check: unknown', 'Cleared: Startup: Service check: unknown',
               'Raised: Service check: offline', 'Cleared: Service check: offline',
               'Raised: Service check: unknown', 'Raised: Startup: Service check: error']
    events = [dict(at='2026-09-14T12:00:00Z', subject='samba', detail=detail,
                   severity='info' if detail.startswith('Cleared') else 'warning') for detail in details]
    monkeypatch.setattr(general, 'display_names', lambda: {'samba': 'Samba'})
    monkeypatch.setattr(general, 'read_telemetry', lambda: {'alert_history': events})
    result = general.get_logs('alerts')
    assert len(result['entries']) == 4
    assert [entry.message for entry in result['entries']] == [
        'Samba is unavailable. Alert raised.',
        'Samba: alert cleared after a current healthy observation (previous check: offline).',
        'Samba availability is unconfirmed. Alert raised.',
        'Raised: Startup: Service check: error',
    ]
    assert result['entries'][1].severity == 'info'
    assert all(entry.timestamp.isoformat() == '2026-09-14T12:00:00+00:00' for entry in result['entries'])
    assert len(events) == 6  # source records are untouched


@pytest.mark.parametrize('subject,transition,expected', [
    ('service:samba', 'online → offline', 'Samba became unavailable (check: offline).'),
    ('samba', 'offline → online', 'Samba recovered.'),
    ('service:jellyfin', 'unknown → online', 'Jellyfin became available.'),
    ('service:samba', 'online → stale', 'Samba: monitoring observation stale; availability is unconfirmed.'),
    ('service checks', 'available → unavailable',
     'Service monitoring observations are unavailable; individual service health is unconfirmed.'),
    ('service checks', 'unavailable → available', 'Service monitoring observations resumed.'),
    ('Storage', 'high → unavailable', 'Storage observation is unavailable; threshold recovery is unconfirmed.'),
])
def test_transition_wording_does_not_invent_a_service_or_cause(subject, transition, expected):
    assert general.human_message(subject, transition, {'samba': 'Samba', 'jellyfin': 'Jellyfin'}) == expected


def test_current_boot_has_consistent_api_semantics(monkeypatch):
    calls = []
    monkeypatch.setattr(server, 'journal_entries', lambda args, *rest: calls.append(args) or [])
    with TestClient(app, raise_server_exceptions=True) as client:
        result = client.get('/api/logs/server?category=current_boot')
        assert result.status_code == 200
        assert 'not just startup' in result.json()['detail']
        assert client.get('/api/logs/server?category=boot').status_code == 422
    assert calls == [['--boot=0']]


def test_samba_default_hides_only_successful_session_accounting(monkeypatch):
    records = [
        row('pam_unix(samba:session): session opened for user fixture(uid=1000)'),
        row('pam_unix(samba:session): session closed for user fixture'),
        row('pam_unix(samba:session): session opened for user fixture', 'warning'),
        row('authentication failed: permission denied', 'warning'),
        row('Started Samba SMB Daemon.'),
        row('Connection failed', 'error'),
    ]
    monkeypatch.setattr(samba, 'journal_entries', lambda *args: records)
    monkeypatch.setattr(samba, 'file_entries', lambda: ([], None))
    assert samba.get_logs()['returned'] == 4
    assert samba.get_logs(category='all')['returned'] == 6
    assert samba.get_logs(severity='warning')['returned'] == 2
    assert samba.get_logs(search='permission')['returned'] == 1


@pytest.mark.parametrize('priority,message,expected', [
    (6, 'audit: apparmor="DENIED" operation="open"', 'warning'),
    (6, 'audit: apparmor="ALLOWED" operation="open"', 'info'),
    (6, 'ordinary application says DENIED', 'info'),
    (3, 'apparmor="DENIED"', 'error'),
])
def test_conservative_operational_severity(priority, message, expected):
    assert common.operational_severity(priority, message) == expected


def test_journal_raw_priority_and_secrets(monkeypatch):
    event = {'__REALTIME_TIMESTAMP': '1789387200000000', 'PRIORITY': '6', 'SYSLOG_IDENTIFIER': 'kernel',
             'MESSAGE': 'apparmor="DENIED" token=private Authorization: Bearer abc'}
    monkeypatch.setattr(common.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr=''))
    result = common.journal_entries([], 50, 'kernel')[0]
    assert result.journal_priority == 6 and result.severity == 'warning'
    assert 'private' not in result.message and 'abc' not in result.message


def test_warning_category_includes_promoted_denials(monkeypatch):
    warning = row('apparmor="DENIED"', 'warning', 'kernel')
    monkeypatch.setattr(server, 'journal_entries', lambda args, *rest:
                        [warning] if '_TRANSPORT=kernel' in args else [])
    assert server.get_logs('warnings')['entries'] == [warning]


@pytest.mark.parametrize('failure', [
    PermissionError('private filesystem info'), subprocess.TimeoutExpired('journalctl', 4),
])
def test_source_failures_are_controlled(monkeypatch, failure):
    def fail(*a, **kw):
        raise failure
    monkeypatch.setattr(common.subprocess, 'run', fail)
    with pytest.raises(common.LogSourceUnavailable):
        common.journal_entries([], 50, 'test')


def test_search_and_extra_paths_cannot_change_source_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(server, 'journal_entries', lambda args, *rest: calls.append(args) or [])
    client = TestClient(app)
    result = client.get('/api/logs/server', params={
        'search': '; cat /etc/shadow', 'file': '/etc/shadow', 'unit': 'anything', 'limit': 200})
    assert result.status_code == 200
    assert calls == [['--since=-24h']]
    assert result.json()['entries'] == []
    assert client.get('/api/logs/server?limit=201').status_code == 422
    assert client.get('/api/logs/samba?category=anything').status_code == 422
