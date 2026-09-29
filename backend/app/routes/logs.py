from typing import Literal
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from app.models.logs import LogResponse
from app.services.logs import general, samba, server
from app.services.logs.common import LogSourceUnavailable


router = APIRouter(prefix='/api/logs', tags=['logs'])
SeverityFilter = Literal['all', 'info', 'warning', 'error']


def provided(operation, *args):
    try:
        return operation(*args)
    except LogSourceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except (OSError, ValueError, sqlite3.Error):
        raise HTTPException(503, 'The requested log source is unavailable') from None


@router.get('/general', response_model=LogResponse)
def general_logs(category: Literal['timeline', 'alerts', 'project'] = 'timeline',
                 severity: SeverityFilter = 'all', search: str = Query(default='', max_length=120),
                 limit: int = Query(default=50, ge=10, le=200)):
    return provided(general.get_logs, category, severity, search, limit)


@router.get('/server', response_model=LogResponse)
def server_logs(category: Literal['all', 'errors', 'warnings', 'current_boot', 'kernel', 'authentication'] = 'all',
                severity: SeverityFilter = 'all', search: str = Query(default='', max_length=120),
                limit: int = Query(default=50, ge=10, le=200)):
    return provided(server.get_logs, category, severity, search, limit)


@router.get('/samba', response_model=LogResponse)
def samba_logs(severity: SeverityFilter = 'all', search: str = Query(default='', max_length=120),
               limit: int = Query(default=50, ge=10, le=200),
               category: Literal['operational', 'all'] = 'operational'):
    return provided(samba.get_logs, severity, search, limit, category)
