"""Bounded read-only mixed API burst: python scripts/benchmark.py --concurrency 100."""
import argparse
import asyncio
import json
import time

import httpx


async def main(args):
    paths = ['/api/health', '/api/system', '/api/services', '/api/catalog']
    semaphore = asyncio.Semaphore(args.concurrency)
    durations = []
    errors = []
    async with httpx.AsyncClient(base_url=args.url, trust_env=False, timeout=15,
                                limits=httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)) as client:
        async def request(index):
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(paths[index % len(paths)])
                    if response.status_code != 200:
                        errors.append(response.status_code)
                except httpx.HTTPError as exc:
                    errors.append(type(exc).__name__)
                durations.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        await asyncio.gather(*(request(i) for i in range(args.requests)))
    durations.sort()
    print(json.dumps({'requests': args.requests, 'concurrency': args.concurrency,
                      'p50_ms': round(durations[len(durations) // 2], 1),
                      'p95_ms': round(durations[int((len(durations)-1)*.95)], 1),
                      'max_ms': round(max(durations), 1), 'errors': errors,
                      'total_seconds': round(time.perf_counter()-started, 2)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8008')
    parser.add_argument('--requests', type=int, default=400, choices=range(1, 2001), metavar='1..2000')
    parser.add_argument('--concurrency', type=int, default=100, choices=range(1, 201), metavar='1..200')
    asyncio.run(main(parser.parse_args()))
