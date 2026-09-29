"""Bounded real, read-only health cycles. Compare fresh-client churn with reuse.

PYTHONPATH=backend backend/.venv/bin/python scripts/profile_monitoring.py --cycles 120
No telemetry/project writes. SSH uses the configured passive adapter.
"""
import argparse
import asyncio
import gc
import json
import tracemalloc

import psutil
from app.services.health import collect_health, health_client


async def run(args):
    process = psutil.Process()
    tracemalloc.start()
    rows = []
    async with health_client() as client:
        previous = None
        for index in range(args.cycles):
            previous = await collect_health(previous=previous, client=None if args.fresh_clients else client)
            if (index + 1) % 20 == 0:
                current, peak = tracemalloc.get_traced_memory()
                row = dict(cycles=index + 1, rss_mib=round(process.memory_info().rss / 1048576, 2),
                           python_live_mib=round(current / 1048576, 2), python_peak_mib=round(peak / 1048576, 2),
                           fds=process.num_fds(), threads=process.num_threads(), gc_counts=gc.get_count())
                rows.append(row)
                print(json.dumps(row), flush=True)
    growth = rows[-1]['rss_mib'] - rows[0]['rss_mib']
    collected = gc.collect()
    print(json.dumps({'fresh_clients': args.fresh_clients, 'post_warmup_rss_growth_mib': growth,
                      'bounded_growth_pass': growth <= args.max_growth_mib,
                      'final_gc_collected': collected, 'rss_after_final_gc_mib': round(process.memory_info().rss / 1048576, 2)}), flush=True)
    if growth > args.max_growth_mib:
        raise SystemExit('Memory growth exceeded budget; investigate before deployment')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=120, choices=range(40, 601))
    parser.add_argument('--fresh-clients', action='store_true')
    parser.add_argument('--max-growth-mib', type=float, default=16)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(run(args), timeout=180))
