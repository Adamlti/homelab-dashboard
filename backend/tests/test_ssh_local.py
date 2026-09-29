import asyncio
import socket
from types import SimpleNamespace

import psutil
import pytest
from pydantic import ValidationError

from app.models.health import LocalSSHProbe, ServiceConfig
from app.services import health, ssh_local


def unit(service='active', socket_state='inactive'):
    return SimpleNamespace(returncode=0, stdout=(
        f'Id=ssh.service\nActiveState={service}\nSubState=running\n\n'
        f'Id=ssh.socket\nActiveState={socket_state}\nSubState=listening\n'), stderr='')


def listener(port=22, ip='0.0.0.0'):
    return SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(ip=ip, port=port))


@pytest.mark.parametrize('active,socket_state,connections,status', [
    ('active', 'inactive', [listener()], 'online'),
    ('inactive', 'active', [listener()], 'online'),
    ('failed', 'inactive', [listener()], 'offline'),
    ('active', 'inactive', [], 'offline'),
    ('active', 'inactive', [listener(2222)], 'offline'),
    ('active', 'inactive', [listener(ip='192.168.1.2')], 'offline'),
])
def test_native_readiness(active, socket_state, connections, status, monkeypatch):
    commands = []
    monkeypatch.setattr(ssh_local.subprocess, 'run',
                        lambda cmd, **kw: commands.append(cmd) or unit(active, socket_state))
    monkeypatch.setattr(ssh_local.psutil, 'net_connections', lambda **kw: connections)
    assert ssh_local.local_ssh_status('127.0.0.1', 22)[0] == status
    assert commands == [['/usr/bin/systemctl', 'show', 'ssh.service', 'ssh.socket',
                         '--property=Id,ActiveState,SubState', '--no-pager']]


def test_passive_probe_never_connects(monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError('Passive health check must not open an SSH connection')
    monkeypatch.setattr(asyncio, 'open_connection', unexpected)
    monkeypatch.setattr(health, 'local_ssh_status', lambda *a: ('online', 'Passive fixture'))
    config = ServiceConfig(id='ssh', name='SSH', description='test',
                           check={'type': 'ssh_local', 'host': '127.0.0.1', 'port': 22})
    result = asyncio.run(health.probe(config))
    assert result.status == 'online' and result.last_success_at


def test_passive_configuration_cannot_target_remote_hosts():
    with pytest.raises(ValidationError):
        LocalSSHProbe(type='ssh_local', host='192.168.1.2', port=22)


def test_listener_permission_failure_is_not_reported_as_service_outage(monkeypatch):
    monkeypatch.setattr(ssh_local.subprocess, 'run', lambda *a, **kw: unit())
    def denied(**kw):
        raise psutil.AccessDenied()
    monkeypatch.setattr(ssh_local.psutil, 'net_connections', denied)
    assert ssh_local.local_ssh_status('127.0.0.1', 22)[0] == 'error'


def test_native_listener_disappears_without_an_active_probe(monkeypatch):
    monkeypatch.setattr(ssh_local.subprocess, 'run', lambda *a, **kw: unit())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        port = sock.getsockname()[1]
        assert ssh_local.local_ssh_status('127.0.0.1', port)[0] == 'online'
    assert ssh_local.local_ssh_status('127.0.0.1', port)[0] == 'offline'
