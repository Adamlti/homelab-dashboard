from datetime import datetime, timezone
import re

import psutil

from app.models.logs import LogEntry
from app.services.audit import list_events as list_audit_events
from app.services.catalog import read_catalog
from app.services.telemetry import read_telemetry

from .common import filter_entries, response, sanitize_message, severity_from_message


RESOURCE_SUBJECTS = {'CPU', 'Memory', 'Storage', 'System', 'Services'}


def display_names():
    catalog = read_catalog()
    return {service['id']: service['name'] for service in catalog['services']}


def source_name(subject, names):
    service_id = subject.removeprefix('service:')
    return names.get(service_id, {'system': 'Server', 'service checks': 'Service checks'}.get(subject, subject))


def mapped_entry(row, names):
    message = human_message(row['subject'], sanitize_message(row['detail']), names)
    severity = row.get('severity', 'info')
    if severity != 'info' and severity_from_message(message) == 'error':
        severity = 'error'
    return LogEntry(timestamp=row['at'], severity=severity, source=source_name(row['subject'], names), message=message)


def human_message(subject, message, names):
    incident = re.fullmatch(r'(Raised|Changed|Cleared|Observation lost): Service check: (\w+)', message)
    service_name = names.get(subject.removeprefix('service:'))
    if incident and service_name:
        action, state = incident.groups()
        if action == 'Observation lost':
            return f'{service_name}: monitoring observation lost; recovery is unconfirmed (last check: {state}).'
        if action == 'Cleared':
            return f'{service_name}: alert cleared after a current healthy observation (previous check: {state}).'
        labels = {'offline': 'is unavailable', 'timeout': 'did not respond before the deadline',
                  'error': 'health check failed', 'unknown': 'availability is unconfirmed', 'stale': 'monitoring observation expired'}
        return f'{service_name} {labels.get(state, "check: " + state)}. Alert {action.lower()}.'
    if ' → ' not in message or message.startswith('Startup:'):
        return message
    previous, current = message.split(' → ', 1)
    service_id = subject.removeprefix('service:')
    if service_id in names:
        name = names[service_id]
        if current in ('unknown', 'stale'):
            return f'{name}: monitoring observation {current}; availability is unconfirmed.'
        if current in ('offline', 'timeout', 'error', 'unavailable'):
            return f'{name} became unavailable (check: {current}).'
        if current == 'online':
            if previous in ('offline', 'timeout', 'error', 'unavailable'):
                return f'{name} recovered.'
            return f'{name} became available.'
        if current == 'not_configured':
            return f'{name}: health monitoring is no longer configured.'
    if subject == 'service checks':
        return ('Service monitoring observations are unavailable; individual service health is unconfirmed.'
                if current == 'unavailable' else 'Service monitoring observations resumed.')
    if subject == 'system':
        return f'Host metrics became {current} (previously {previous}).'
    if subject in ('CPU', 'Memory', 'Storage'):
        if current == 'high':
            return f'{subject} usage crossed the alert threshold.'
        if current == 'normal':
            return f'{subject} usage returned below the alert threshold.'
        return f'{subject} observation is unavailable; threshold recovery is unconfirmed.'
    return message


def startup_alert(row):
    # Suppress only the recorded initialization incident, including its cleanup.
    # Real unknown/stale observations and startup failures remain available.
    return row['detail'] in {
        f'{prefix}: Startup: Service check: unknown'
        for prefix in ('Raised', 'Cleared', 'Changed', 'Observation lost')
    }


def get_logs(category='timeline', severity='all', search='', limit=50):
    names = display_names()
    if category == 'project':
        rows = list_audit_events()
        entries = [LogEntry(timestamp=row['at'], severity='info', source=row['subject'],
                            message=sanitize_message(row['detail'])) for row in rows]
        sources = ['Dashboard SQLite project edit history']
        detail = 'Project edits are recorded without an authenticated actor.'
    else:
        history = read_telemetry()
        if category == 'alerts':
            entries = [mapped_entry(row, names) for row in history['alert_history'] if not startup_alert(row)]
            sources = ['Dashboard alert transition history']
            detail = 'Raised, changed, cleared, and lost observations; initialization-only unknown incidents are excluded.'
        else:
            entries = [LogEntry(timestamp=datetime.fromtimestamp(psutil.boot_time(), timezone.utc),
                                severity='info', source='Server', message='Host booted.')]
            seen = set()
            for row in history['events']:
                # Normal initial observations are startup noise, not meaningful timeline events.
                if (row['detail'].startswith('First observation')
                        or row['detail'].startswith('Startup:')
                        or row['detail'].startswith('unknown → ')
                        or row['detail'].endswith(' → unknown')):
                    continue
                entry = mapped_entry(row, names)
                key = (entry.timestamp, entry.source, entry.message)
                if key not in seen:
                    entries.append(entry)
                    seen.add(key)
            for row in history['alert_history']:
                if row['subject'] not in RESOURCE_SUBJECTS or startup_alert(row):
                    continue
                entry = mapped_entry(row, names)
                key = (entry.timestamp, entry.source, entry.message)
                if key not in seen:
                    entries.append(entry)
                    seen.add(key)
            sources = ['Dashboard service-state events', 'Dashboard resource alert transitions', 'Host boot timestamp']
            detail = 'Curated state changes and threshold events; routine raw service logs are excluded.'
    entries = filter_entries(entries, severity, search, limit)
    return response('general', entries, limit, sources, detail)
