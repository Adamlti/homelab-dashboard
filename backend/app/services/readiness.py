"""Bounded dependency checks; no host mutations or synchronous sampling."""

import sqlite3

from app.services.catalog import read_catalog
from app.services.system import MetricsUnavailable, read_system
from app.services.tasks import database_path


def storage_ready():
    # mode=rw avoids silently creating a replacement for a missing database.
    connection = sqlite3.connect(database_path().resolve().as_uri() + '?mode=rw', uri=True, timeout=0.2)
    try:
        connection.execute('SELECT id, title, completed, created_at FROM tasks LIMIT 1')
        connection.execute('SELECT id, title, description, phase, position FROM roadmap LIMIT 1')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("INSERT OR REPLACE INTO metadata VALUES ('readiness_probe', '1')")
        # Exercise the write path without persisting a change.
        connection.rollback()
    finally:
        connection.close()


def readiness(state):
    dependencies = {}
    checks = {
        'sqlite': (storage_ready, 'Project storage unavailable, locked, or not writable'),
        'catalog': (read_catalog, 'Service catalog unavailable or invalid'),
        'system': (lambda: read_system(getattr(getattr(state, 'system_monitor', None), 'snapshot', None)),
                   'System metrics missing or stale; check the collector or sampler'),
        'service_checks': (lambda: check_services(state), 'Service observations missing, stale, or configuration-mismatched'),
    }
    for name, (check, detail) in checks.items():
        try:
            check()
            dependencies[name] = {'status': 'healthy'}
        except (OSError, sqlite3.Error, ValueError, MetricsUnavailable):
            dependencies[name] = {'status': 'unhealthy', 'detail': detail}
    ready = all(value['status'] == 'healthy' for value in dependencies.values())
    return {'status': 'ready' if ready else 'not_ready', 'dependencies': dependencies}


def check_services(state):
    monitor = getattr(state, 'health_monitor', None)
    if monitor is None:
        raise ValueError('Monitor not initialized')
    rows = monitor.read()['services']
    # An observed outage is valid monitoring data; unknown/expired data is not.
    if any(row['status'] in ('unknown', 'stale') for row in rows):
        raise ValueError('Observations unavailable')
