import sqlite3
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.tasks import Task, TaskCreate, TaskUpdate
from app.services import tasks

router = APIRouter(prefix='/api/tasks', tags=['tasks'])


def require_dashboard_request(request: Request):
    # Custom header + JSON requires CORS preflight for cross-site browser requests.
    # No CORS access is granted. The header is not an authentication secret.
    if request.headers.get('x-dashboard-request') != 'tasks':
        raise HTTPException(403, 'Dashboard request header required')
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'JSON required')
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Cross-origin project writes are not allowed')


def stored(operation, *args):
    try:
        return operation(*args)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, 'Project storage unavailable') from exc
    except LookupError as exc:
        raise HTTPException(404, 'Item not found') from exc
    except OverflowError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('', response_model=list[Task])
def list_tasks():
    return stored(tasks.list_tasks)


@router.post('', response_model=Task, status_code=201, dependencies=[Depends(require_dashboard_request)])
def add_task(task: TaskCreate):
    return stored(tasks.add_task, task.title)


@router.patch('/{task_id}', response_model=Task, dependencies=[Depends(require_dashboard_request)])
def update_task(task_id: UUID, task: TaskUpdate):
    return stored(tasks.update_task, task_id, task.model_dump(exclude_unset=True))


@router.delete('/{task_id}', dependencies=[Depends(require_dashboard_request)])
def remove_task(task_id: UUID):
    return stored(tasks.remove_task, task_id)
