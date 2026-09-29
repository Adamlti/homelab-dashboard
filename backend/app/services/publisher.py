"""Exclusive host publisher. API host mode and optional collector share this lock."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def publisher_lock():
    path = Path(os.getenv('DASHBOARD_PUBLISHER_LOCK', str(
        Path(__file__).resolve().parents[3] / 'data/monitoring.lock')))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another host publisher is running; use either the native API or the collector') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
