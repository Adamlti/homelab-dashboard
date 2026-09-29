"""Passive native SSH readiness. Never connects, logs in, or controls a unit."""
import ipaddress
import subprocess

import psutil


def local_ssh_status(host, port):
    # Both units are fixed: ssh.socket can legitimately await activation of ssh.service.
    result = subprocess.run(
        ['/usr/bin/systemctl', 'show', 'ssh.service', 'ssh.socket',
         '--property=Id,ActiveState,SubState', '--no-pager'],
        capture_output=True, text=True, timeout=1, check=False,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
    )
    if result.returncode:
        return 'error', 'Local SSH unit state unavailable'
    units = [dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
             for block in result.stdout.strip().split('\n\n')]
    ready = any(unit.get('ActiveState') == 'active' and (
        (unit.get('Id') == 'ssh.service' and unit.get('SubState') == 'running') or
        (unit.get('Id') == 'ssh.socket' and unit.get('SubState') in ('listening', 'running'))
    ) for unit in units)
    if not ready:
        return 'offline', 'Local SSH service and socket are not ready'
    address = ipaddress.ip_address(host)
    try:
        connections = psutil.net_connections(kind='tcp')
    except (psutil.Error, OSError):
        return 'error', 'Local SSH listener information unavailable'
    for connection in connections:
        if connection.status != psutil.CONN_LISTEN or connection.laddr.port != port:
            continue
        listening = ipaddress.ip_address(connection.laddr.ip)
        if listening == address or (listening.is_unspecified and listening.version == address.version):
            return 'online', 'Local SSH unit ready and TCP listener present; passive check, login not tested'
    return 'offline', 'Local SSH unit active but configured listener is absent'
