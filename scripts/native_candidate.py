"""Start/stop an isolated, hardened candidate without touching live services.

Uses unique transient user units, separate loopback ports and a disposable DB.
The fixed state file is only an operator test convenience, never an API input.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data/native-candidate.json'


def start():
    if STATE.exists():
        raise SystemExit('Candidate state already exists; stop it first')
    folder = Path(tempfile.mkdtemp(prefix='.native-test-', dir=ROOT / 'data'))
    token = uuid4().hex[:8]
    units = [f'adamserv-test-api-{token}', f'adamserv-test-web-{token}']
    catalog = json.loads((ROOT / 'config/catalog.json').read_text())
    catalog.update(tasks=[], roadmap=[])
    (folder / 'catalog.json').write_text(json.dumps(catalog))
    shutil.copyfile(ROOT / 'data/metrics/history.json', folder / 'history.json')
    release = ROOT / 'frontend/releases' / ('candidate-' + token)
    shutil.copytree(ROOT / 'frontend/dist', release)
    state = {'directory': str(folder), 'units': units, 'release': str(release), 'url': 'http://127.0.0.1:18088'}
    STATE.write_text(json.dumps(state, indent=2))
    try:
        for kind, unit, module, port in zip(('api', 'web'), units, ('app.main:app', 'app.frontend:app'), (18008, 18088)):
            # Apply the same [Service] hardening as the permanent units.
            properties = []
            for line in (ROOT / f'config/adamserv-dashboard-{kind}.service').read_text().splitlines():
                if line.startswith(('NoNewPrivileges=', 'PrivateUsers=', 'PrivateTmp=', 'ProtectSystem=', 'ProtectHome=', 'CapabilityBoundingSet=', 'AmbientCapabilities=', 'RestrictSUIDSGID=', 'LockPersonality=', 'RestrictAddressFamilies=', 'UMask=', 'TimeoutStopSec=')):
                    properties.append('--property=' + line)
            if kind == 'api':
                properties.append('--property=ReadWritePaths=' + str(folder))
            environment = {
                'DASHBOARD_METRICS_MODE': 'host', 'DASHBOARD_TASKS_PATH': str(folder / 'tasks.sqlite3'),
                'DASHBOARD_HISTORY_PATH': str(folder / 'history.json'), 'DASHBOARD_CATALOG_PATH': str(folder / 'catalog.json'),
                'DASHBOARD_PUBLISHER_LOCK': str(folder / 'publisher.lock'),
                'DASHBOARD_BACKUP_STATUS_PATH': str(folder / 'no-backup.json'),
                'DASHBOARD_FRONTEND_DIST': str(release), 'DASHBOARD_API_PORT': '18008', 'PYTHONDONTWRITEBYTECODE': '1',
            }
            subprocess.run(['systemd-run', '--user', '--unit=' + unit, '--collect', '--property=RuntimeMaxSec=1800',
                '--working-directory=' + str(ROOT / 'backend'), *properties,
                *['--setenv=' + key + '=' + value for key, value in environment.items()],
                str(ROOT / 'backend/.venv/bin/python'), '-m', 'uvicorn', module, '--host', '127.0.0.1', '--port', str(port),
                '--no-access-log', '--no-proxy-headers'], check=True)
        for _ in range(30):
            try:
                with urlopen(state['url'] + '/api/ready', timeout=2) as result:
                    if json.load(result)['status'] == 'ready':
                        print(json.dumps(state), flush=True)
                        return
            except OSError:
                time.sleep(1)
                if any(subprocess.run(['systemctl', '--user', 'is-active', '--quiet', unit]).returncode for unit in units):
                    break
        raise RuntimeError('Candidate did not become ready')
    except BaseException:
        for unit in units:
            subprocess.run(['journalctl', '--user', '-u', unit, '-n', '20', '--no-pager'], check=False)
        stop()
        raise


def stop():
    state = json.loads(STATE.read_text())
    # Never accept service names or storage paths outside this test namespace.
    assert all(unit.startswith(('adamserv-test-api-', 'adamserv-test-web-')) for unit in state['units'])
    folder = Path(state['directory'])
    assert folder.parent == ROOT / 'data' and folder.name.startswith('.native-test-')
    for unit in state['units']:
        result = subprocess.run(['systemctl', '--user', 'stop', unit], capture_output=True, text=True)
        if result.returncode and 'not loaded' not in result.stderr:
            raise RuntimeError(result.stderr)
    shutil.rmtree(folder)
    STATE.unlink()
    print('Candidate services stopped; isolated DB removed; verified release retained at ' + state['release'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    args = parser.parse_args()
    (start if args.action == 'start' else stop)()
