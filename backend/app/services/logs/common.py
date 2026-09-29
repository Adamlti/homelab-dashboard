import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.models.logs import LogEntry


JOURNALCTL = Path('/usr/bin/journalctl')
MAX_SCAN = 800
MAX_CAPTURE_CHARS = 2_000_000
_SECRET_ASSIGNMENT = re.compile(
    r'(?i)\b(password|passwd|passphrase|token|secret|api[-_ ]?key|authorization|cookie|credential)'
    r'\b\s*[:=]\s*(?:"[^"]*"|\'[^\']*\'|[^\s,;]+)'
)
_BEARER = re.compile(r'(?i)\bbearer\s+[a-z0-9._~+/=-]+')
_BASIC = re.compile(r'(?i)\bbasic\s+[a-z0-9+/=]+')
_AUTH_HEADER = re.compile(r'(?i)\bauthorization\s*[:=]\s*(?:basic|bearer)\s+[a-z0-9._~+/=-]+')
_URL_PASSWORD = re.compile(r'(?i)(https?://[^\s:/@]+:)[^\s/@]+(@)')
_PRIVATE_KEY = re.compile(r'(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----')


class LogSourceUnavailable(RuntimeError):
    pass


def sanitize_message(value, *, limit=1200):
    message = str(value).replace('\x00', ' ')
    message = ' '.join(message.splitlines())
    message = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', message)
    message = re.sub(r'\s+', ' ', message).strip()
    if _PRIVATE_KEY.search(message):
        return '[Sensitive private key material redacted]'
    message = _AUTH_HEADER.sub('Authorization=[REDACTED]', message)
    message = _SECRET_ASSIGNMENT.sub(lambda match: f'{match.group(1)}=[REDACTED]', message)
    message = _BEARER.sub('Bearer [REDACTED]', message)
    message = _BASIC.sub('Basic [REDACTED]', message)
    message = _URL_PASSWORD.sub(r'\1[REDACTED]\2', message)
    return message if limit is None else message[:limit]


def severity_from_priority(priority):
    try:
        value = int(priority)
    except (TypeError, ValueError):
        return 'info'
    if value <= 3:
        return 'error'
    if value == 4:
        return 'warning'
    return 'info'


def severity_from_message(message):
    lowered = message.casefold()
    if re.search(r'\b(error|fatal|panic|corrupt|failure)\b', lowered):
        return 'error'
    if re.search(r'\b(warn(?:ing)?|failed|denied|unavailable|timeout|stale)\b', lowered):
        return 'warning'
    return 'info'


def operational_severity(priority, message):
    severity = severity_from_priority(priority)
    # AppArmor audit denials can carry informational journal priority.
    if severity == 'info' and re.search(r'\bapparmor="DENIED"', message, re.IGNORECASE):
        return 'warning'
    return severity


def filter_entries(entries, severity='all', search='', limit=50):
    query = search.casefold().strip()
    filtered = (
        entry for entry in entries
        if (severity == 'all' or entry.severity == severity)
        and (not query or query in f'{entry.source} {entry.message}'.casefold())
    )
    return sorted(filtered, key=lambda entry: entry.timestamp, reverse=True)[:limit]


def journal_entries(arguments, scan_limit, default_source):
    if not JOURNALCTL.is_file():
        raise LogSourceUnavailable('The system journal reader is not installed')
    scan_limit = min(MAX_SCAN, max(50, scan_limit))
    command = [
        str(JOURNALCTL), '--quiet', '--no-pager', '--output=json', '--reverse',
        f'--lines={scan_limit}',
        '--output-fields=__REALTIME_TIMESTAMP,_SOURCE_REALTIME_TIMESTAMP,PRIORITY,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT,MESSAGE',
        *arguments,
    ]
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors='replace',
                                timeout=4, check=False, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LogSourceUnavailable('The system journal did not respond within its safe deadline') from exc
    if result.returncode:
        error = result.stderr.casefold()
        if 'permission' in error or 'access' in error:
            raise LogSourceUnavailable('The dashboard user does not have permission to read this journal source')
        raise LogSourceUnavailable('The requested system journal source is unavailable')
    if len(result.stdout) > MAX_CAPTURE_CHARS:
        raise LogSourceUnavailable('The bounded journal response exceeded the dashboard safety limit')
    entries = []
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
            stamp = row.get('__REALTIME_TIMESTAMP') or row.get('_SOURCE_REALTIME_TIMESTAMP')
            timestamp = datetime.fromtimestamp(int(stamp) / 1_000_000, timezone.utc)
            message = sanitize_message(row.get('MESSAGE', ''))
        except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
            continue
        if not message:
            continue
        source = sanitize_message(row.get('SYSLOG_IDENTIFIER') or row.get('_SYSTEMD_UNIT') or default_source)
        try:
            priority = int(row.get('PRIORITY'))
            if not 0 <= priority <= 7:
                priority = None
        except (TypeError, ValueError):
            priority = None
        entries.append(LogEntry(timestamp=timestamp, severity=operational_severity(priority, message),
                                journal_priority=priority, source=source[:80] or default_source, message=message))
    return entries


def response(provider, entries, limit, sources, detail=None):
    return {
        'provider': provider,
        'generated_at': datetime.now(timezone.utc),
        'entries': entries,
        'returned': len(entries),
        'limit': limit,
        'sources': sources,
        'detail': detail,
    }
