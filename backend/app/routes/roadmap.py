from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.catalog import RoadmapItem
from app.routes.tasks import require_dashboard_request, stored
from app.services import roadmap

router = APIRouter(prefix='/api/roadmap', tags=['roadmap'])
write_guard = [Depends(require_dashboard_request)]


class Entry(RoadmapItem):
    id: UUID
    position: int


class Order(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ids: list[UUID] = Field(max_length=100)

    @field_validator('ids')
    @classmethod
    def unique(cls, ids):
        if len(ids) != len(set(ids)):
            raise ValueError('IDs must be unique')
        return ids


@router.get('', response_model=list[Entry])
def list_items():
    return stored(roadmap.list_items)


@router.post('', response_model=Entry, status_code=201, dependencies=write_guard)
def add_item(item: RoadmapItem):
    return stored(roadmap.add_item, item.model_dump())


@router.put('/order', response_model=list[Entry], dependencies=write_guard)
def reorder(order: Order):
    return stored(roadmap.reorder, order.ids)


@router.patch('/{item_id}', response_model=Entry, dependencies=write_guard)
def update_item(item_id: UUID, item: RoadmapItem):
    return stored(roadmap.update_item, item_id, item.model_dump())


@router.delete('/{item_id}', dependencies=write_guard)
def remove_item(item_id: UUID):
    return stored(roadmap.remove_item, item_id)
