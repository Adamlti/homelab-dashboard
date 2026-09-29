from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Memory(BaseModel):
    total: int = Field(gt=0)
    used: int = Field(ge=0)
    available: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class Disk(BaseModel):
    path: str
    total: int = Field(gt=0)
    used: int = Field(ge=0)
    free: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class NetworkInterface(BaseModel):
    name: str
    addresses: list[str]
    is_up: bool | None = None
    speed_mbps: int | None = Field(default=None, ge=0)
    rx_bytes_per_second: float | None = Field(default=None, ge=0)
    tx_bytes_per_second: float | None = Field(default=None, ge=0)
    errors_in: int | None = Field(default=None, ge=0)
    errors_out: int | None = Field(default=None, ge=0)
    drops_in: int | None = Field(default=None, ge=0)
    drops_out: int | None = Field(default=None, ge=0)


class SystemSnapshot(BaseModel):
    hostname: str
    os: str
    kernel: str
    sampled_at: datetime
    source: Literal["host", "collector"] = "host"
    uptime_seconds: float = Field(ge=0)
    cpu_percent: float = Field(ge=0, le=100)
    cpu_count: int = Field(gt=0)
    memory: Memory
    load_average: list[float] = Field(min_length=3, max_length=3)
    disks: list[Disk]
    network: list[NetworkInterface]
    warnings: list[str] = []
