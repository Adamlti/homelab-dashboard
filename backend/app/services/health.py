"""Bounded HTTP/TCP probes and cached, age-aware service results."""

import asyncio
import logging
import os
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.models.health import HealthSnapshot, HTTPProbe, SSHProbe, LocalSSHProbe, ProbeResult, config_hash
from app.services.catalog import catalog_model
from app.services.ssh_local import local_ssh_status

INTERVAL_SECONDS = 10
STALE_AFTER_SECONDS = 30
logger = logging.getLogger(__name__)


def service_configs():
    return catalog_model().services


def health_client():
    # One TLS context/pool per publisher, not one per target per ten seconds.
    return httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=3,
                             limits=httpx.Limits(max_connections=8, max_keepalive_connections=8))


async def probe(service, client=None) -> ProbeResult:
    check = service.check
    if check is None:
        return ProbeResult(id=service.id, status='not_configured', detail='No health adapter configured')
    if isinstance(check, HTTPProbe) and client is None:
        async with health_client() as owned_client:
            return await probe(service, owned_client)
    started = time.monotonic()
    status, detail, http_status = 'error', 'Probe failed', None
    try:
        # A total deadline also bounds TLS, headers and slow-drip responses.
        async with asyncio.timeout(check.timeout_seconds):
            if isinstance(check, LocalSSHProbe):
                status, detail = await asyncio.to_thread(local_ssh_status, check.host, check.port)
            elif isinstance(check, HTTPProbe):
                # No proxy env, redirects, credentials or response-body download.
                async with client.stream('GET', check.url, timeout=check.timeout_seconds) as response:
                    http_status = response.status_code
                    accepted = http_status in check.expected_statuses
                    status = 'online' if accepted else 'offline'
                    detail = f'HTTP {http_status}' + ('' if accepted else ' (unexpected status)')
            else:
                reader, writer = await asyncio.open_connection(check.host, check.port, limit=512)
                try:
                    if isinstance(check, SSHProbe):
                        status, detail = 'error', 'No supported SSH protocol greeting'
                        for _ in range(8):
                            line = await reader.readline()
                            if not line:
                                break
                            if line.startswith((b'SSH-2.0-', b'SSH-1.99-')) and line.endswith(b'\n'):
                                status, detail = 'online', 'SSH protocol greeting received; login not attempted'
                                break
                    else:
                        status, detail = 'online', 'TCP port reachable; application health not verified'
                finally:
                    writer.close()
                    await writer.wait_closed()
    except (TimeoutError, httpx.TimeoutException, subprocess.TimeoutExpired):
        status, detail = 'timeout', f'No result within {check.timeout_seconds:g}s deadline'
    except PermissionError:
        status, detail = 'error', 'Health observation permission denied'
    except (OSError, httpx.ConnectError):
        status, detail = 'offline', 'Connection failed (refused, unreachable or TLS verification failed)'
    except ValueError:
        status, detail = 'error', 'Protocol greeting exceeded the allowed size'
    except httpx.HTTPError:
        status, detail = 'error', 'HTTP protocol error'
    checked_at = datetime.now(timezone.utc)
    return ProbeResult(id=service.id, status=status, detail=detail,
                       checked_at=checked_at, last_success_at=checked_at if status == 'online' else None, http_status=http_status,
                       latency_ms=round((time.monotonic() - started) * 1000, 1))


async def collect_health(services=None, previous=None, client=None) -> HealthSnapshot:
    services = service_configs() if services is None else services
    semaphore = asyncio.Semaphore(8)

    async def limited(service):
        async with semaphore:
            return await probe(service, client)

    results = await asyncio.gather(*(limited(service) for service in services))
    retain_success(results, previous, services)
    return HealthSnapshot(config_hash=config_hash(services), services=results)


def retain_success(results, previous, services):
    if previous is not None and previous.config_hash == config_hash(services):
        old = {result.id: result for result in previous.services}
        for result in results:
            if result.last_success_at is None and result.id in old:
                result.last_success_at = old[result.id].last_success_at


def health_view(snapshot, services, now=None):
    now = now or datetime.now(timezone.utc)
    matching = snapshot is not None and snapshot.config_hash == config_hash(services)
    results = {result.id: result for result in snapshot.services} if matching else {}
    rows = []
    for service in services:
        row = {'id': service.id, 'type': service.check.type if service.check else None,
               'timeout_seconds': service.check.timeout_seconds if service.check else None,
               'status': 'unknown', 'last_status': None, 'stale': False,
               'checked_at': None, 'last_success_at': None, 'age_seconds': None, 'latency_ms': None, 'http_status': None,
               'detail': 'Waiting for a check of the current configuration'}
        result = results.get(service.id)
        if service.check is None:
            row.update(status='not_configured', detail='No health adapter configured')
        elif result and result.checked_at:
            row.update(result.model_dump(mode='json'))
            age = (now - result.checked_at).total_seconds()
            row['age_seconds'] = round(max(0, age), 1)
            row['stale'] = age > STALE_AFTER_SECONDS or age < -5
            if row['stale']:
                row.update(status='stale', last_status=result.status,
                           detail=f'Check expired; last result: {result.status}. {result.detail}')
        rows.append(row)
    return {'services': rows, 'stale_after_seconds': STALE_AFTER_SECONDS,
            'refresh_interval_seconds': INTERVAL_SECONDS}


class HealthMonitor:
    def __init__(self):
        self.snapshot = None

    async def run(self):
        async with health_client() as client:
            await self.collect_forever(client)

    async def collect_forever(self, client):
        while True:
            try:
                self.snapshot = await collect_health(previous=self.snapshot, client=client)
            except Exception:
                # Retain the last observation; its timestamp will expire normally.
                logger.exception('Service health collection failed')
            await asyncio.sleep(INTERVAL_SECONDS)

    def read(self):
        services = service_configs()
        mode = os.getenv('DASHBOARD_METRICS_MODE', 'host')
        if mode == 'collector':
            path = Path(os.getenv('DASHBOARD_SERVICES_SNAPSHOT_PATH',
                                 str(Path(os.getenv('DASHBOARD_SNAPSHOT_PATH', '/data/system.json')).with_name('services.json'))))
            if path.stat().st_size > 1_048_576:
                raise ValueError('Service snapshot too large')
            snapshot = HealthSnapshot.model_validate_json(path.read_text())
        elif mode == 'host':
            snapshot = self.snapshot
        else:
            raise ValueError('Invalid metrics mode')
        return health_view(snapshot, services)
