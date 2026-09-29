from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models.system import SystemSnapshot
from app.services.catalog import read_catalog
from app.services.system import MetricsUnavailable, read_system
from app.services.readiness import readiness
from app.services.telemetry import read_telemetry
from app.services.backup_status import read_backup_status

router = APIRouter(prefix="/api")


@router.get('/backups')
async def backups(request: Request):
    if hasattr(request.app.state, 'response_cache'): return request.app.state.response_cache.response(request.url.path)
    return read_backup_status()


@router.get('/history')
async def history(request: Request):
    if hasattr(request.app.state, 'response_cache'): return request.app.state.response_cache.response(request.url.path)
    try:
        return read_telemetry()
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Monitoring history unavailable; check collector publication') from exc


@router.get('/ready')
async def ready(request: Request):
    if hasattr(request.app.state, 'response_cache'): return request.app.state.response_cache.response(request.url.path)
    result = readiness(request.app.state)
    return JSONResponse(result, status_code=200 if result['status'] == 'ready' else 503)


@router.get("/health")
async def health():
    return {"status": "ok", "service": "adamserv-dashboard", "read_only": False,
            "host_read_only": True, "writable_features": ["tasks", "roadmap", "notes"]}


@router.get("/system", response_model=SystemSnapshot)
async def system(request: Request):
    if hasattr(request.app.state, 'response_cache'): return request.app.state.response_cache.response(request.url.path)
    try:
        return read_system(getattr(request.app.state, 'system_monitor', None).snapshot
                           if hasattr(request.app.state, 'system_monitor') else None)
    except MetricsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="System metrics temporarily unavailable") from exc


@router.get("/catalog")
async def catalog(request: Request):
    if hasattr(request.app.state, 'response_cache'): return request.app.state.response_cache.response(request.url.path)
    try:
        return read_catalog()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Service catalog unavailable") from exc


@router.get('/services')
async def services(request: Request):
    if hasattr(request.app.state, 'response_cache'): return request.app.state.response_cache.response(request.url.path)
    try:
        return request.app.state.health_monitor.read()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail='Service checks unavailable; check the catalog and collector') from exc


@router.get('/audit')
def audit():
    from app.routes.tasks import stored
    from app.services.audit import list_events
    return stored(list_events)
