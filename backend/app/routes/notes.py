import sqlite3

from fastapi import APIRouter, Depends

from app.models.notes import Notes, NotesUpdate
from app.routes.tasks import require_dashboard_request, stored
from app.services import notes

router = APIRouter(prefix='/api/notes', tags=['notes'])
write_guard = [Depends(require_dashboard_request)]


@router.get('', response_model=Notes)
def read_notes():
    return stored(notes.read_notes)


@router.patch('', response_model=Notes, dependencies=write_guard)
def update_notes(payload: NotesUpdate):
    return stored(notes.update_notes, payload.content)
