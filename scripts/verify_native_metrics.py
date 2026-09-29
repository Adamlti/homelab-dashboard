"""Read-only comparisons against direct host observations; no synthetic project data."""
import json
import os
import time
from datetime import datetime, timezone
from urllib.request import urlopen

import psutil


def get(path):
    with urlopen(os.getenv('DASHBOARD_VERIFY_URL', 'http://127.0.0.1:18088') + path, timeout=5) as response:
        return json.load(response)


results = []
for _ in range(3):
    sample = get('/api/system')
    memory = psutil.virtual_memory()
    direct_cpu = psutil.cpu_percent(interval=.2)
    uptime = time.time() - psutil.boot_time()
    load = os.getloadavg()
    counters = psutil.net_io_counters(pernic=True, nowrap=False)
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    assert abs(sample['uptime_seconds'] - uptime) < 8
    assert sample['memory']['total'] == memory.total
    assert abs(sample['memory']['used'] - (memory.total - memory.available)) < 512 * 1024**2
    assert sample['cpu_count'] == psutil.cpu_count() and 0 <= sample['cpu_percent'] <= 100
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(sample['sampled_at'].replace('Z', '+00:00'))).total_seconds()
    assert 0 <= age < 8
    for disk in sample['disks']:
        direct = psutil.disk_usage(disk['path'])
        assert disk['total'] == direct.total and abs(disk['used'] - direct.used) < 64 * 1024**2
    for interface in sample['network']:
        name = interface['name']
        assert interface['is_up'] == stats[name].isup
        assert set(interface['addresses']) <= {address.address for address in addresses[name]}
        for api_key, host_key in [('errors_in', 'errin'), ('errors_out', 'errout'), ('drops_in', 'dropin'), ('drops_out', 'dropout')]:
            # Cached counters can precede this direct read by six seconds.
            assert 0 <= interface[api_key] <= getattr(counters[name], host_key)
    results.append({'sampled_at': sample['sampled_at'], 'age_seconds': round(age, 2),
                    'cpu_dashboard_direct': [sample['cpu_percent'], direct_cpu],
                    'memory_used_dashboard_direct': [sample['memory']['used'], memory.total - memory.available],
                    'uptime_dashboard_direct': [sample['uptime_seconds'], uptime],
                    'load_dashboard_direct': [sample['load_average'], load],
                    'disks': sample['disks'], 'network': sample['network'],
                    'network_direct': {row['name']: counters[row['name']]._asdict() for row in sample['network']}})
    time.sleep(5)
print(json.dumps({'status': 'PASS', 'scope': 'CPU/load are adjacent sampling windows, not simultaneous measurements; network rates are deltas while error/drop counters are lifetime totals.', 'samples': results}, indent=2))
