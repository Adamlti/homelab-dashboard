"""Read-only native checks. No SSH connections or project mutations are made."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen


def get(path, **params):
    with urlopen(os.getenv('DASHBOARD_VERIFY_URL', 'http://127.0.0.1:8008') + path + ('?' + urlencode(params) if params else ''), timeout=12) as result:
        return json.load(result)


def main():
    start = datetime.now(timezone.utc)
    evidence = {}
    checks = [
        ('general', 'timeline'), ('general', 'alerts'), ('general', 'project'),
        ('server', 'all'), ('server', 'current_boot'), ('server', 'kernel'),
        ('server', 'warnings'), ('server', 'errors'), ('server', 'authentication'),
        ('samba', 'operational'), ('samba', 'all'),
    ]
    for provider, category in checks:
        data = get('/api/logs/' + provider, category=category, limit=200)
        assert data['returned'] == len(data['entries']) <= 200
        times = [datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')) for row in data['entries']]
        assert times == sorted(times, reverse=True)
        assert all(stamp.tzinfo and stamp <= datetime.now(timezone.utc) for stamp in times)
        if provider == 'general' and category == 'alerts':
            assert not any('Startup: Service check: unknown' in row['message'] for row in data['entries'])
        evidence[provider + '/' + category] = data['returned']

    operational = get('/api/logs/samba', category='operational', limit=200)['entries']
    all_samba = get('/api/logs/samba', category='all', limit=200)['entries']
    routine = lambda row: 'pam_unix(samba:session): session ' in row['message'] and row['severity'] == 'info'
    assert not any(map(routine, operational))
    # Retention/quiet periods may legitimately contain no session records.
    # Independently check that any routine records within the displayed window
    # are preserved by All, rather than demanding that the host had activity.
    source = subprocess.run(
        ['/usr/bin/journalctl', '--unit=smbd.service', '--since=-7d', '--lines=800',
         '--output=json', '--output-fields=MESSAGE,PRIORITY,__REALTIME_TIMESTAMP', '--no-pager'],
        capture_output=True, text=True, check=True, timeout=4)
    cutoff = min((datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                  for row in all_samba), default=None)
    expected_routine = []
    for line in source.stdout.splitlines():
        if not line.startswith('{'):
            continue
        record = json.loads(line)
        if 'pam_unix(samba:session): session ' not in record.get('MESSAGE', ''):
            continue
        stamp = datetime.fromtimestamp(int(record['__REALTIME_TIMESTAMP']) / 1_000_000, timezone.utc)
        if cutoff is None or stamp >= cutoff:
            expected_routine.append(record['MESSAGE'])
    assert all(any(row['message'] == message for row in all_samba) for message in expected_routine), 'Samba All omitted a routine source record'
    evidence['routine_samba_records_in_current_window'] = sum(map(routine, all_samba))
    evidence['routine_samba_source_records_checked'] = len(expected_routine)

    # Compare a real retained authentication event with the unmodified source.
    journal = subprocess.run(
        ['/usr/bin/journalctl', '--boot=0', '--unit=ssh.service', '--grep=Accepted',
         '--lines=1', '--output=json', '--output-fields=MESSAGE', '--no-pager'],
        capture_output=True, text=True, check=True, timeout=4)
    accepted = [json.loads(line)['MESSAGE'] for line in journal.stdout.splitlines() if line.startswith('{')]
    assert accepted, 'No retained real successful SSH login available for comparison'
    auth = get('/api/logs/server', category='authentication', search='Accepted', limit=200)['entries']
    assert any(row['message'] == accepted[-1] for row in auth), 'Real SSH login missing from Authentication view'
    evidence['real_authentication_preserved'] = True

    samples = set()
    # Observe several monitoring cycles, rather than checking just one cached result.
    for _ in range(8):
        ssh = next(row for row in get('/api/services')['services'] if row['id'] == 'ssh')
        assert ssh['type'] == 'ssh_local' and ssh['status'] == 'online'
        assert 'passive check' in ssh['detail']
        samples.add(ssh['checked_at'])
        time.sleep(5)
    assert len(samples) >= 3
    noise = subprocess.run(
        ['/usr/bin/journalctl', '--unit=ssh.service', '--since=' + start.isoformat(),
         '--output=json', '--output-fields=MESSAGE', '--no-pager'],
        capture_output=True, text=True, check=True, timeout=4)
    messages = [json.loads(line).get('MESSAGE', '') for line in noise.stdout.splitlines() if line.startswith('{')]
    count = sum('Connection closed by 127.0.0.1 port ' in message for message in messages)
    assert count == 0, f'Observed {count} loopback SSH session-close events during passive monitoring'
    evidence.update(passive_ssh_samples=len(samples), observation_seconds=round((datetime.now(timezone.utc)-start).total_seconds()),
                    loopback_ssh_close_events=count)
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
