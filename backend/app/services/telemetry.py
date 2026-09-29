"""Bounded resource history and monitoring events, derived only from existing DTOs."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from functools import lru_cache

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.services.system import MetricsUnavailable, read_system

MAX_POINTS = 4320
MAX_EVENTS = 100
RETENTION = timedelta(hours=72)


class Point(BaseModel):
    model_config = ConfigDict(extra='forbid')
    at: AwareDatetime
    cpu: float = Field(ge=0, le=100)
    memory: float = Field(ge=0, le=100)
    disk: float | None = Field(default=None, ge=0, le=100)


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid')
    at: AwareDatetime
    subject: str = Field(max_length=80)
    detail: str = Field(max_length=160)
    severity: Literal['info', 'warning'] = 'info'


class TelemetrySnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sampled_at: AwareDatetime
    points: list[Point] = Field(default_factory=list, max_length=MAX_POINTS)
    events: list[Event] = Field(default_factory=list, max_length=MAX_EVENTS)
    alerts: list[Event] = Field(default_factory=list, max_length=32)
    alert_history: list[Event] = Field(default_factory=list, max_length=MAX_EVENTS)
    states: dict[str, str] = Field(default_factory=dict, max_length=32)


def telemetry_path():
    default = Path(__file__).resolve().parents[3] / 'data/native/history.json'
    if os.getenv('DASHBOARD_METRICS_MODE', 'host') == 'collector':
        default = Path(os.getenv('DASHBOARD_SNAPSHOT_PATH', '/data/system.json')).with_name('history.json')
    return Path(os.getenv('DASHBOARD_HISTORY_PATH', str(default)))


def load_history(path):
    stat = path.stat()
    if stat.st_size > 1_048_576:
        raise ValueError('History exceeds size limit')
    # Readers replace filtered lists, so do not expose the cached model itself.
    return validated_history(str(path), (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)).model_copy()


@lru_cache(maxsize=1)
def validated_history(path, fingerprint):
    return TelemetrySnapshot.model_validate_json(Path(path).read_text())


class Telemetry:
    def __init__(self, path):
        self.path = path
        self.first_observation = True
        self.thresholds = {}
        for name, default in (('CPU', 90), ('Memory', 90), ('Storage', 85)):
            value = float(os.getenv('DASHBOARD_ALERT_' + name.upper(), str(default)))
            if not 0 < value <= 100:
                raise ValueError('Alert thresholds must be greater than zero and at most 100')
            self.thresholds[name] = value
        try:
            self.snapshot = load_history(path)
        except (OSError, ValueError):
            self.snapshot = TelemetrySnapshot(sampled_at=datetime.now(timezone.utc))

    def observe(self, system, services, now=None):
        now = now or datetime.now(timezone.utc)
        cutoff = now - RETENTION
        points = [point for point in self.snapshot.points if cutoff <= point.at <= now + timedelta(seconds=5)]
        events = [event for event in self.snapshot.events if cutoff <= event.at <= now + timedelta(seconds=5)]
        alert_history = [event for event in self.snapshot.alert_history if cutoff <= event.at <= now + timedelta(seconds=5)]
        alerts, states = [], {}
        valid_system = system is not None and system.sampled_at.tzinfo is not None and -5 <= (now - system.sampled_at).total_seconds() <= 30
        states['system'] = 'available' if valid_system else 'unavailable'
        if valid_system:
            point = Point(at=system.sampled_at, cpu=system.cpu_percent, memory=system.memory.percent,
                          disk=max((disk.percent for disk in system.disks), default=None))
            # Keep one actual observation per minute, not an invented average.
            if not points or point.at >= points[-1].at + timedelta(seconds=60):
                points.append(point)
            for name, value in (('CPU', point.cpu), ('Memory', point.memory), ('Storage', point.disk)):
                threshold = self.thresholds[name]
                states[name] = 'high' if value is not None and value >= threshold else 'normal' if value is not None else 'unavailable'
                if states[name] == 'high':
                    alerts.append(Event(at=now, subject=name, severity='warning', detail=f'{value:.1f}% used (threshold {threshold}%)'))
        else:
            alerts.append(Event(at=now, subject='System', severity='warning', detail='Metrics unavailable or stale'))
        states['service checks'] = 'available' if services is not None else 'unavailable'
        if services is None:
            alerts.append(Event(at=now, subject='Services', severity='warning', detail='Service observations unavailable'))
        else:
            for row in services['services']:
                key, status = 'service:' + row['id'], row['status']
                states[key] = status
                if status in ('offline', 'timeout', 'error', 'unknown', 'stale'):
                    alerts.append(Event(at=now, subject=row['id'], severity='warning', detail=f'{"Startup: " if self.first_observation and status == "unknown" else ""}Service check: {status}'))
        for subject, status in states.items():
            previous = self.snapshot.states.get(subject)
            if previous != status:
                events.append(Event(at=now, subject=subject,
                                    detail=f'{"Startup: " if self.first_observation and status == "unknown" else ""}{previous or "First observation"} → {status}',
                                    severity='warning' if status in ('unavailable', 'high', 'offline', 'timeout', 'error', 'unknown', 'stale') else 'info'))
        previous_alerts = {alert.subject: alert for alert in self.snapshot.alerts}
        current_alerts = {alert.subject: alert for alert in alerts}
        for subject, alert in current_alerts.items():
            previous = previous_alerts.get(subject)
            if previous is None:
                alert_history.append(Event(at=now, subject=subject, detail=f'Raised: {alert.detail}', severity='warning'))
            elif subject not in ('CPU', 'Memory', 'Storage') and previous.detail != alert.detail:
                alert_history.append(Event(at=now, subject=subject, detail=f'Changed: {alert.detail}', severity='warning'))
        for subject, alert in previous_alerts.items():
            if subject not in current_alerts:
                # Missing resource data does not prove a threshold alert recovered.
                unavailable = subject in ('CPU', 'Memory', 'Storage') and not valid_system
                if subject == 'Storage' and valid_system and not system.disks:
                    unavailable = True
                if subject not in ('CPU', 'Memory', 'Storage', 'System', 'Services'):
                    observed = next((row for row in services['services'] if row['id'] == subject), None) if services is not None else None
                    unavailable = observed is None or observed['status'] == 'not_configured'
                prefix = 'Observation lost' if unavailable else 'Cleared'
                alert_history.append(Event(at=now, subject=subject, detail=f'{prefix}: {alert.detail}', severity='warning' if unavailable else 'info'))
        self.snapshot = TelemetrySnapshot(sampled_at=now, points=points[-MAX_POINTS:], events=events[-MAX_EVENTS:], alerts=alerts, alert_history=alert_history[-MAX_EVENTS:], states=states)
        self.first_observation = False
        return self.snapshot


def read_telemetry(path=None, now=None):
    now = now or datetime.now(timezone.utc)
    snapshot = load_history(path or telemetry_path())
    age = (now - snapshot.sampled_at).total_seconds()
    # Enforce the display window even while the collector is stopped.
    snapshot.points = [point for point in snapshot.points if now - RETENTION <= point.at <= now + timedelta(seconds=5)]
    snapshot.events = [event for event in snapshot.events if now - RETENTION <= event.at <= now + timedelta(seconds=5)]
    snapshot.alert_history = [event for event in snapshot.alert_history if now - RETENTION <= event.at <= now + timedelta(seconds=5)]
    result = snapshot.model_dump(mode='json', exclude={'states'})
    result.update(stale=age < -5 or age > 30, age_seconds=round(max(0, age), 1), retention_hours=72,
                  max_points=MAX_POINTS, max_events=MAX_EVENTS)
    return result


async def monitor_history(state):
    # Native development mode publishes to the same bounded snapshot format.
    from app.collector import write_json
    history = Telemetry(telemetry_path())
    while True:
        try:
            try:
                system = read_system(state.system_monitor.snapshot)
            except (OSError, MetricsUnavailable):
                system = None
            try:
                services = state.health_monitor.read()
            except (OSError, ValueError):
                services = None
            snapshot = history.observe(system, services)
            await asyncio.to_thread(write_json, history.path, snapshot)
        except Exception:
            logging.getLogger(__name__).exception('History publication failed')
        await asyncio.sleep(10)
