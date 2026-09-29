"""Isolate read-route ASGI latency from Uvicorn, TCP and client connections.

PYTHONPATH=backend backend/.venv/bin/python scripts/profile_asgi.py --output data/asgi-profile-NEW.json
Uses temporary synthetic snapshots; does not probe services or change live data.
"""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time

import httpx
import psutil

from app.main import app
from app.models.health import HealthSnapshot, ProbeResult, config_hash
from app.models.system import SystemSnapshot
from app.services.catalog import catalog_model
from app.services.health import HealthMonitor


async def profile(directory):
    configs = catalog_model().services
    os.environ['DASHBOARD_METRICS_MODE'] = 'collector'
    os.environ['DASHBOARD_SNAPSHOT_PATH'] = str(directory / 'system.json')
    os.environ['DASHBOARD_SERVICES_SNAPSHOT_PATH'] = str(directory / 'services.json')
    app.state.health_monitor = HealthMonitor()
    paths = ['/api/health', '/api/system', '/api/services', '/api/catalog']
    results = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        for concurrency in (4, 100, 100, 100):
            stamp = datetime.now(timezone.utc)
            system = SystemSnapshot(hostname='profile-fixture', os='Ubuntu fixture', kernel='fixture', sampled_at=stamp,
                                    uptime_seconds=100, cpu_percent=20, cpu_count=4,
                                    memory={'total': 1000, 'used': 400, 'available': 600, 'percent': 40},
                                    load_average=[0, 0, 0], disks=[], network=[])
            (directory / 'system.json').write_text(system.model_dump_json())
            snapshot = HealthSnapshot(config_hash=config_hash(configs), services=[ProbeResult(id=config.id, status='online' if config.check else 'not_configured', detail='Synthetic profile observation', checked_at=stamp if config.check else None) for config in configs])
            (directory / 'services.json').write_text(snapshot.model_dump_json())
            semaphore = asyncio.Semaphore(concurrency)
            timings, errors = [], []
            async def request(index):
                async with semaphore:
                    before = time.perf_counter()
                    response = await client.get(paths[index % len(paths)])
                    timings.append((time.perf_counter() - before) * 1000)
                    if response.status_code != 200:
                        errors.append(response.status_code)
            start = time.monotonic()
            await asyncio.gather(*(request(index) for index in range(400)))
            timings.sort()
            result = {'concurrency': concurrency, 'requests': 400, 'p50_ms': timings[200], 'p95_ms': timings[379],
                      'max_ms': timings[-1], 'seconds': time.monotonic() - start, 'errors': errors,
                      'rss_bytes': psutil.Process().memory_info().rss}
            results.append(result)
            print(json.dumps(result), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output filename')
    with tempfile.TemporaryDirectory(prefix='dashboard-asgi-profile-') as temporary:
        results = asyncio.run(profile(Path(temporary)))
    report = {'scope': 'Direct ASGI read routes with synthetic snapshots; excludes TCP/Uvicorn/Nginx, SQLite routes and a long-duration soak', 'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
