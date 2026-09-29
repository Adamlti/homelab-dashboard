import socket
from types import SimpleNamespace

from app.services.system import network_interfaces


def test_default_filters_inactive_virtual_and_link_local_keeps_vpn():
    addresses = {name: [SimpleNamespace(address=ip, family=socket.AF_INET)] for name, ip in {
        'lo': '127.0.0.1', 'docker0': '172.17.0.1', 'veth123': '10.0.0.2',
        'enp1s0': '192.168.1.10', 'wlan0': '192.168.1.11', 'wg0': '10.20.0.1',
        'enp2s0': '169.254.0.1',
    }.items()}
    stats = {name: SimpleNamespace(isup=name != 'wlan0') for name in addresses}
    assert [item.name for item in network_interfaces(addresses, stats)] == ['enp1s0', 'wg0']
    assert len(network_interfaces(addresses, stats, '*')) == 7
    assert [item.name for item in network_interfaces(addresses, stats, 'lo,wlan0')] == ['lo', 'wlan0']


def test_ipv6_link_local_zone_and_addressless_interface():
    addresses = {'enp1s0': [SimpleNamespace(address='fe80::1%enp1s0', family=socket.AF_INET6)], 'tun0': []}
    stats = {name: SimpleNamespace(isup=True) for name in addresses}
    assert network_interfaces(addresses, stats) == []
