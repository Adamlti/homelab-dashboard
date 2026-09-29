"""Fixed, read-only OS queries. No subprocesses or client-selected paths."""

import asyncio
import logging
import ipaddress
import os
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path

import psutil

from app.services.network import rates
from app.models.system import Disk, Memory, NetworkInterface, SystemSnapshot


def network_interfaces(address_map, stats, selection='auto'):
    """Default to active LAN/VPN interfaces; operator can explicitly include any."""
    result = []
    selected = {name.strip() for name in selection.split(',')}
    for name, addresses in address_map.items():
        ips = [a.address for a in addresses if a.family in (socket.AF_INET, socket.AF_INET6)]
        if selection == 'auto':
            if name.startswith(('lo', 'veth', 'docker', 'br-', 'virbr')) or not getattr(stats.get(name), 'isup', False):
                continue
            ips = [ip for ip in ips if not ipaddress.ip_address(ip.split('%')[0]).is_loopback
                   and not ipaddress.ip_address(ip.split('%')[0]).is_link_local]
            if not ips:
                continue
        elif selection != '*' and name not in selected:
            continue
        result.append(NetworkInterface(name=name, addresses=ips, is_up=getattr(stats.get(name), 'isup', None), speed_mbps=max(0, getattr(stats.get(name), 'speed', 0)) or None))
    return sorted(result, key=lambda interface: interface.name)


def collect_system() -> SystemSnapshot:
    warnings = []
    memory = psutil.virtual_memory()
    disks = []
    # Paths are operator configuration, never supplied by an API request.
    for path in dict.fromkeys(os.getenv("DASHBOARD_DISK_PATHS", "/").split(":")):
        try:
            usage = psutil.disk_usage(path)
            disks.append(Disk(path=path, **usage._asdict()))
        except OSError:
            warnings.append(f"Storage metrics unavailable for {path}")
    network = []
    try:
        network = network_interfaces(psutil.net_if_addrs(), psutil.net_if_stats(),
                                     os.getenv('DASHBOARD_NETWORK_INTERFACES', 'auto'))
        traffic = rates.sample(psutil.net_io_counters(pernic=True, nowrap=False))
        network = [interface.model_copy(update=traffic.get(interface.name, {})) for interface in network]
    except (OSError, psutil.Error):
        warnings.append("Network addresses unavailable in this execution environment")
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", platform.system())
    except OSError:
        os_name = platform.system()
    return SystemSnapshot(
        hostname=socket.gethostname(), os=os_name, kernel=platform.release(),
        sampled_at=datetime.now(timezone.utc),
        uptime_seconds=max(0, datetime.now(timezone.utc).timestamp() - psutil.boot_time()),
        cpu_percent=psutil.cpu_percent(interval=0.2), cpu_count=psutil.cpu_count() or 1,
        # Used = total - available, consistent with psutil's percentage (excludes reclaimable cache).
        memory=Memory(total=memory.total, used=memory.total - memory.available,
                      available=memory.available, percent=memory.percent),
        load_average=list(os.getloadavg()), disks=disks, network=network, warnings=warnings,
    )


class MetricsUnavailable(Exception):
    pass


class SystemMonitor:
    def __init__(self):
        self.snapshot = None

    async def sample(self):
        if Path('/.dockerenv').exists():
            return
        try:
            self.snapshot = await asyncio.to_thread(collect_system)
        except Exception:
            logging.getLogger(__name__).exception('System sampling failed')

    async def run(self):
        while True:
            await asyncio.sleep(5)
            await self.sample()


def read_system(cached=None) -> SystemSnapshot:
    mode = os.getenv("DASHBOARD_METRICS_MODE", "host")
    if mode == "host":
        if Path("/.dockerenv").exists():
            raise MetricsUnavailable("Container deployment requires collector mode for real host metrics")
        if cached is None:
            raise MetricsUnavailable('Waiting for the background system sample')
        age = (datetime.now(timezone.utc) - cached.sampled_at).total_seconds()
        if age < -5 or age > 30:
            raise MetricsUnavailable('System sampler is stale')
        return cached
    if mode != "collector":
        raise MetricsUnavailable("Invalid metrics mode")
    path = Path(os.getenv("DASHBOARD_SNAPSHOT_PATH", "/data/system.json"))
    try:
        if path.stat().st_size > 1_048_576:
            raise ValueError("Snapshot too large")
        snapshot = SystemSnapshot.model_validate_json(path.read_text())
        if snapshot.sampled_at.tzinfo is None:
            raise ValueError("Missing timestamp timezone")
        age = (datetime.now(timezone.utc) - snapshot.sampled_at).total_seconds()
        if age < -5 or age > 30:
            raise MetricsUnavailable("Host metrics are stale; check the host collector")
        snapshot.source = "collector"
        return snapshot
    except (OSError, ValueError) as exc:
        raise MetricsUnavailable("Host snapshot unavailable; start the host collector") from exc
