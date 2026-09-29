"""Offline retention/read-path profile; does not measure live HTTP latency.

PYTHONPATH=backend backend/.venv/bin/python scripts/profile_history.py --output data/history-profile.json
Uses generated DTOs in a temporary directory; never publishes host metrics.
"""
import argparse
import gc
import json
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psutil

from app.collector import write_json
from app.services.telemetry import Telemetry, read_telemetry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output filename; existing evidence is never overwritten')
    started = time.monotonic()
    observations = []
    process = psutil.Process()
    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix='dashboard-history-profile-') as temporary:
        path = Path(temporary) / 'history.json'
        history = Telemetry(path)
        origin = datetime.now(timezone.utc) - timedelta(days=5)
        for index in range(5761):
            stamp = origin + timedelta(minutes=index)
            system = SimpleNamespace(sampled_at=stamp, cpu_percent=20, memory=SimpleNamespace(percent=40), disks=[SimpleNamespace(percent=60)])
            services = {'services': [{'id': 'ssh', 'status': 'online' if index % 2 else 'offline'}]}
            history.observe(system, services, stamp)
            if index % 1440 == 0:
                gc.collect()
                current, peak = tracemalloc.get_traced_memory()
                row = {'observations': index + 1, 'points': len(history.snapshot.points), 'events': len(history.snapshot.events),
                       'python_live_bytes': current, 'python_peak_bytes': peak, 'rss_bytes': process.memory_info().rss}
                observations.append(row)
                print(json.dumps(row), flush=True)
        write_json(path, history.snapshot)
        tracemalloc.stop()
        durations = []
        for _ in range(1000):
            before = time.perf_counter()
            result = read_telemetry(path, stamp)
            durations.append((time.perf_counter() - before) * 1000)
        durations.sort()
        report = {'scope': 'Offline generated telemetry retention and sequential read path; not live HTTP or long-duration process evidence',
                  'memory': observations, 'snapshot_bytes': path.stat().st_size, 'returned_points': len(result['points']),
                  'read_iterations': len(durations), 'read_p50_ms': statistics.median(durations),
                  'read_p95_ms': durations[int((len(durations)-1) * .95)], 'elapsed_seconds': time.monotonic() - started}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
