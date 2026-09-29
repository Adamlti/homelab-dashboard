"""Run as adam on the host; atomically publish only an allowlisted metrics DTO."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from app.services.system import collect_system
from app.services.health import collect_health, health_view, service_configs, health_client
from app.services.publisher import publisher_lock
from app.models.health import HealthSnapshot
from app.services.telemetry import Telemetry


def write_snapshot(output: Path):
    snapshot = collect_system()
    snapshot.source = "collector"
    write_json(output, snapshot)
    return snapshot


def write_json(output: Path, snapshot) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(snapshot.model_dump_json() + "\n")
    temporary.chmod(0o644)
    os.replace(temporary, output)


async def collect_loop(args):
    with publisher_lock():
        async with health_client() as client:
            await publish_loop(args, client)


async def publish_loop(args, client):
    previous = None
    services_path = args.output.with_name('services.json')
    history = Telemetry(Path(os.getenv('DASHBOARD_HISTORY_PATH', str(args.output.with_name('history.json')))))
    try:
        if services_path.stat().st_size <= 1_048_576:
            previous = HealthSnapshot.model_validate_json(services_path.read_text())
    except (OSError, ValueError):
        pass
    while True:
        system, services = None, None
        for kind in ('system', 'services'):
            try:
                if kind == 'system':
                    system = await asyncio.to_thread(write_snapshot, args.output)
                else:
                    previous = await collect_health(previous=previous, client=client)
                    write_json(services_path, previous)
                    services = health_view(previous, service_configs())
            except Exception:
                logging.exception('%s collection failed', kind)
                if args.once:
                    raise
        try:
            write_json(history.path, history.observe(system, services))
        except Exception:
            logging.exception('History publication failed')
            if args.once:
                raise
        if args.once:
            break
        await asyncio.sleep(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[2] / "data/metrics/system.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        asyncio.run(collect_loop(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
