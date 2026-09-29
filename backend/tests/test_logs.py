import json
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.models.logs import LogEntry
from app.routes import logs as log_routes
from app.services.logs import general, samba, server
from app.services.logs.common import LogSourceUnavailable, filter_entries, journal_entries, response, sanitize_message


def entry(message='A real event', severity='info', source='test'):
    return LogEntry(timestamp=datetime.now(timezone.utc), severity=severity, source=source, message=message)


def test_message_sanitization_redacts_common_secret_shapes():
    message = sanitize_message('token=abc Bearer xyz https://user:pass@example.test/path password: "hidden" Authorization: Basic YWJj')
    assert 'abc' not in message
    assert 'xyz' not in message
    assert 'pass@' not in message
    assert 'hidden' not in message
    assert 'YWJj' not in message
    assert message.count('[REDACTED]') == 5
    assert sanitize_message('-----BEGIN PRIVATE KEY----- material') == '[Sensitive private key material redacted]'


def test_filtering_search_severity_sort_and_limit():
    older = LogEntry(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), severity='warning', source='disk', message='Nearly full')
    newer = LogEntry(timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc), severity='warning', source='smbd', message='Client timeout')
    assert filter_entries([older, newer, entry(severity='info')], 'warning', '', 1) == [newer]
    assert filter_entries([older, newer], 'all', 'DISK', 50) == [older]


def test_journal_reader_uses_fixed_structured_fields(monkeypatch, tmp_path):
    binary = tmp_path / 'journalctl'
    binary.write_text('')
    monkeypatch.setattr('app.services.logs.common.JOURNALCTL', binary)
    stamp = int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp() * 1_000_000)
    output = json.dumps({
        '__REALTIME_TIMESTAMP': str(stamp),
        'PRIORITY': '3',
        'SYSLOG_IDENTIFIER': 'kernel',
        'MESSAGE': 'Disk error',
    })
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=0, stdout=output, stderr='')

    monkeypatch.setattr('app.services.logs.common.subprocess.run', run)
    rows = journal_entries(['--boot=0', '--dmesg'], 100, 'systemd')
    assert rows[0].severity == 'error'
    assert rows[0].source == 'kernel'
    assert '--output=json' in captured['command']
    assert '--boot=0' in captured['command']
    assert captured['kwargs']['timeout'] == 4
    assert captured['kwargs']['env'] == {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}


def test_server_categories_never_put_search_text_in_journal_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(server, 'journal_entries', lambda arguments, scan_limit, source: calls.append(arguments) or [entry('Needle')])
    result = server.get_logs('kernel', 'all', 'Needle', 25)
    assert result['returned'] == 1
    assert calls == [['--boot=0', '--dmesg']]


def test_general_logs_remove_routine_startup_noise_and_keep_real_alerts(monkeypatch):
    monkeypatch.setattr(general.psutil, 'boot_time', lambda: datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(general, 'read_catalog', lambda: {'services': [{'id': 'samba', 'name': 'Samba'}]})
    monkeypatch.setattr(general, 'read_telemetry', lambda: {
        'events': [
            {'at': '2026-01-01T00:00:00Z', 'subject': 'system', 'detail': 'First observation → available', 'severity': 'info'},
            {'at': '2026-01-01T00:00:30Z', 'subject': 'samba', 'detail': 'Startup: online → unknown', 'severity': 'warning'},
            {'at': '2026-01-01T00:00:40Z', 'subject': 'samba', 'detail': 'unknown → online', 'severity': 'info'},
            {'at': '2026-01-01T00:00:50Z', 'subject': 'samba', 'detail': 'online → unknown', 'severity': 'warning'},
            {'at': '2026-01-01T00:01:00Z', 'subject': 'samba', 'detail': 'online → offline', 'severity': 'warning'},
        ],
        'alert_history': [
            {'at': '2026-01-01T00:01:00Z', 'subject': 'CPU', 'detail': 'Raised: 95.0% used (threshold 90%)', 'severity': 'warning'},
        ],
    })
    result = general.get_logs('timeline')
    assert {'Samba', 'CPU', 'Server'} == {row.source for row in result['entries']}
    assert all('First observation' not in row.message for row in result['entries'])
    assert all('Startup:' not in row.message and 'unknown' not in row.message for row in result['entries'])
    assert next(row for row in result['entries'] if row.source == 'Samba').message.startswith('Samba became unavailable')


def test_samba_file_parser_reads_only_supplied_fixed_file_shape(tmp_path):
    log = tmp_path / 'log.smbd'
    log.write_text('[2026/09/14 01:02:03.123456,  0] module.c:10(start)\n  smbd started cleanly\n')
    rows, detail = samba.file_entries(log)
    assert detail is None
    assert len(rows) == 1
    assert rows[0].timestamp.tzinfo is not None
    assert rows[0].source == 'smbd file'
    assert rows[0].message == 'module.c:10(start) smbd started cleanly'


def test_log_routes_validate_filters_and_report_source_failures(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(log_routes.server, 'get_logs', lambda *args: response('server', [entry()], args[-1], ['test source']))
    success = client.get('/api/logs/server?category=kernel&severity=warning&search=disk&limit=25')
    assert success.status_code == 200
    assert success.json()['provider'] == 'server'
    assert client.get('/api/logs/server?category=arbitrary').status_code == 422
    assert client.get('/api/logs/server?limit=500').status_code == 422

    def unavailable(*args):
        raise LogSourceUnavailable('Approved journal source is unavailable')

    monkeypatch.setattr(log_routes.samba, 'get_logs', unavailable)
    failed = client.get('/api/logs/samba')
    assert failed.status_code == 503
    assert failed.json() == {'detail': 'Approved journal source is unavailable'}


def test_log_routes_are_read_only():
    client = TestClient(app)
    for path in ('/api/logs/general', '/api/logs/server', '/api/logs/samba'):
        for method in ('post', 'put', 'patch', 'delete'):
            assert getattr(client, method)(path).status_code == 405
