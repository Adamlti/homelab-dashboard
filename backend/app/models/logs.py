from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


Severity = Literal['info', 'warning', 'error']


class LogEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    timestamp: AwareDatetime
    severity: Severity
    source: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=1200)
    journal_priority: int | None = Field(default=None, ge=0, le=7)


class LogResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['general', 'server', 'samba']
    generated_at: AwareDatetime
    entries: list[LogEntry] = Field(max_length=200)
    returned: int = Field(ge=0, le=200)
    limit: int = Field(ge=10, le=200)
    sources: list[str] = Field(min_length=1, max_length=8)
    detail: str | None = Field(default=None, max_length=300)
