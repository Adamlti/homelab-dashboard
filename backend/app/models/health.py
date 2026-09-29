"""Operator-controlled, fixed destinations. No request-provided probe targets."""

import hashlib
import ipaddress
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1/128', 'fc00::/7',
))


def local_address(value: str) -> str:
    address = ipaddress.ip_address(value)
    if not any(address in network for network in NETWORKS):
        raise ValueError('Probe targets must be literal loopback or private LAN IP addresses')
    return value


class ProbeBase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    timeout_seconds: float = Field(default=2, ge=0.1, le=3)


class HTTPProbe(ProbeBase):
    type: Literal['http']
    url: str = Field(max_length=512)
    expected_statuses: list[int] = Field(default=[200], min_length=1, max_length=20)

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('Only HTTP(S) URLs are supported')
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Credentials, queries and fragments are not supported')
        local_address(parsed.hostname)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError('Invalid port')
        return value

    @field_validator('expected_statuses')
    @classmethod
    def valid_statuses(cls, values):
        if any(not 200 <= value <= 599 for value in values):
            raise ValueError('Invalid HTTP response status')
        return values


class TCPProbe(ProbeBase):
    type: Literal['tcp']
    host: str
    port: int = Field(ge=1, le=65535)

    @field_validator('host')
    @classmethod
    def safe_host(cls, value):
        return local_address(value)


class SSHProbe(TCPProbe):
    type: Literal['ssh']


class LocalSSHProbe(TCPProbe):
    type: Literal['ssh_local']

    @field_validator('host')
    @classmethod
    def loopback_only(cls, value):
        if not ipaddress.ip_address(value).is_loopback:
            raise ValueError('Passive SSH checks require a loopback address on this host')
        return value


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z0-9_-]{1,40}$')
    name: str
    description: str
    url: str | None = None
    link_warning: str | None = Field(default=None, max_length=500)
    check: Annotated[HTTPProbe | TCPProbe | SSHProbe | LocalSSHProbe, Field(discriminator='type')] | None = None


class ServiceList(BaseModel):
    services: list[ServiceConfig] = Field(max_length=16)

    @field_validator('services')
    @classmethod
    def unique_ids(cls, services):
        if len({service.id for service in services}) != len(services):
            raise ValueError('Service IDs must be unique')
        return services


def config_hash(services: list[ServiceConfig]) -> str:
    data = [service.model_dump(mode='json') for service in services]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class ProbeResult(BaseModel):
    id: str
    status: Literal['online', 'offline', 'timeout', 'error', 'not_configured']
    detail: str
    checked_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    http_status: int | None = None


class HealthSnapshot(BaseModel):
    config_hash: str
    services: list[ProbeResult] = Field(max_length=16)
