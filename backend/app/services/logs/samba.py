import re
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

from app.models.logs import LogEntry

from .common import LogSourceUnavailable, filter_entries, journal_entries, response, sanitize_message, severity_from_message


SAMBA_LOG = Path('/var/log/samba/log.smbd')
_HEADER = re.compile(r'^\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d+),\s*\d+\]')


def file_entries(path=SAMBA_LOG):
    try:
        if not path.is_file():
            return [], 'Samba file log is not present'
        if path.stat().st_size > 2_000_000:
            return [], 'Samba file log exceeds the dashboard safety limit'
        lines = path.read_text(errors='replace').splitlines()
    except PermissionError as exc:
        raise LogSourceUnavailable('The dashboard user cannot read the approved Samba log file') from exc
    except OSError as exc:
        raise LogSourceUnavailable('The approved Samba log file is unavailable') from exc
    entries = deque(maxlen=800)
    timestamp = None
    message_parts = []

    def publish():
        if timestamp is None:
            return
        raw = ' '.join(message_parts)
        # Redact the complete bounded record BEFORE splitting or shortening it.
        message = sanitize_message(raw, limit=None)
        if message == '[Sensitive private key material redacted]':
            parts = [message]
        else:
            # Some Samba builds concatenate many warnings on one physical line.
            parts = [part.strip() for part in re.split(
                r'(?=\b(?:WARNING|WARN|ERROR|FATAL|PANIC):)', message, flags=re.IGNORECASE) if part.strip()]
            if len(parts) == 1 and len(message) > 600:
                parts = [sanitize_message(part, limit=None) for part in message_parts if part.strip()]
        # Counts apply only within this timestamped file record, not across time.
        for part, count in Counter(parts).items():
            if not part:
                continue
            summary = f'Repeated {count} times in this file record: {part}' if count > 1 else part
            if len(summary) > 600:
                summary = summary[:540] + f'… [{len(summary) - 540} more characters omitted]'
            entries.append(LogEntry(timestamp=timestamp, severity=severity_from_message(part),
                                    source='smbd file', message=summary))

    for line in lines:
        match = _HEADER.match(line)
        if match:
            publish()
            timestamp = datetime.strptime(match.group(1), '%Y/%m/%d %H:%M:%S.%f').astimezone()
            remainder = line[match.end():].strip()
            message_parts = [remainder] if remainder else []
        elif timestamp is not None and line.strip():
            message_parts.append(line.strip())
    publish()
    return list(entries), None


def routine_session(entry):
    # Only successful PAM accounting records. Failures and denials stay visible.
    return entry.severity == 'info' and bool(re.search(
        r'pam_unix\(samba:session\): session (?:opened|closed) for user\b',
        entry.message, re.IGNORECASE))


def get_logs(severity='all', search='', limit=50, category='operational'):
    errors = []
    entries = []
    try:
        entries.extend(journal_entries(['--since=-7d', '--unit=smbd.service'], min(800, max(100, limit * 4)), 'smbd'))
    except LogSourceUnavailable as exc:
        errors.append(str(exc))
    try:
        file_rows, file_detail = file_entries()
        entries.extend(file_rows)
        if file_detail:
            errors.append(file_detail)
    except LogSourceUnavailable as exc:
        errors.append(str(exc))
    if not entries and len(errors) == 2:
        raise LogSourceUnavailable('Samba journal and approved file log are unavailable')
    if category == 'operational':
        entries = [entry for entry in entries if not routine_session(entry)]
    entries = filter_entries(entries, severity, search, limit)
    detail = ('Journal: 7 days. Current file: last 800 records/lines, ≤2 MB; no age cutoff or rotated files. '
              'Samba controls retention. Split warnings share a header timestamp; repeats are counted.')
    if category == 'operational':
        detail += ' Routine PAM sessions hidden; All includes them.'
    if errors:
        detail += ' Partial source: ' + '; '.join(errors)
    return response('samba', entries, limit,
                    ['systemd journal: smbd.service', '/var/log/samba/log.smbd'], detail[:300])
