"""One background serialization pass serves all readers; never cache Project writes."""
import asyncio
from dataclasses import dataclass
import json
import logging
import time

from starlette.responses import Response

from app.services.backup_status import read_backup_status
from app.services.catalog import read_catalog
from app.services.readiness import readiness
from app.services.system import read_system, MetricsUnavailable
from app.services.telemetry import read_telemetry


@dataclass(frozen=True)
class Entry:
    body: bytes
    status: int
    built_at: float


class ResponseCache:
    def __init__(self, state):
        self.state = state
        self.entries = {}
        self.last_data = {}
        self.serializations = 0
        self.reuses = 0
        self.last_slow_refresh = 0

    def refresh(self, force=True):
        now = time.monotonic()
        slow_due = force or now - self.last_slow_refresh >= 5
        operations = {
            '/api/system': lambda: read_system(self.state.system_monitor.snapshot).model_dump(mode='json'),
            '/api/catalog': read_catalog,
            '/api/services': self.state.health_monitor.read,
            '/api/history': read_telemetry,
            '/api/backups': read_backup_status,
            '/api/ready': lambda: readiness(self.state),
        }
        entries = {}
        for path, read in operations.items():
            if path in ('/api/backups', '/api/ready') and not slow_due:
                entries[path] = self.entries[path]
                continue
            try:
                data = read()
                status = 503 if path == '/api/ready' and data['status'] != 'ready' else 200
            except (OSError, ValueError, MetricsUnavailable):
                data, status = {'detail': f'{path.removeprefix("/api/").capitalize()} data unavailable; check collector/configuration'}, 503
            previous = self.entries.get(path)
            if previous is not None and self.last_data.get(path) == data and previous.status == status:
                body = previous.body
                self.reuses += 1
            else:
                body = json.dumps(data, separators=(',', ':'), allow_nan=False).encode()
                self.serializations += 1
            self.last_data[path] = data
            entries[path] = Entry(body, status, time.monotonic())
        self.entries = entries
        if slow_due:
            self.last_slow_refresh = now

    def response(self, path):
        entry = self.entries.get(path)
        ttl = 7 if path in ('/api/backups', '/api/ready') else 2
        if entry is None or time.monotonic() - entry.built_at > ttl:
            return Response(b'{"detail":"Monitoring cache is stale; check the backend"}', status_code=503, media_type='application/json')
        return Response(entry.body, status_code=entry.status, media_type='application/json')

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.refresh, False)
            except Exception:
                # Never extend the lifetime of old success responses after a failed refresh.
                logging.getLogger(__name__).exception('Monitoring response cache refresh failed')
            await asyncio.sleep(1)


class ResponseHeaders:
    """Pure ASGI headers avoid a task/stream per request in BaseHTTPMiddleware."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_headers(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                headers = [(key, value) for key, value in message.get('headers', []) if key.lower() not in (b'cache-control', b'x-content-type-options')]
                message['headers'] = headers + [(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')]
            await send(message)
        await self.app(scope, receive, send_headers)
