from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.health import ServiceList


class RoadmapItem(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=1000)
    phase: str = Field(min_length=1, max_length=40)


class Catalog(ServiceList):
    model_config = ConfigDict(extra='forbid')
    roadmap: list[RoadmapItem] = Field(max_length=100)
    tasks: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]] = Field(max_length=1000)
