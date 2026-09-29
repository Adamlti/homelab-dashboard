import asyncio
import os
import logging
import sqlite3
from contextlib import asynccontextmanager, suppress, ExitStack

from fastapi import FastAPI

from app.routes.api import router
from app.routes.tasks import router as tasks_router
from app.routes.roadmap import router as roadmap_router
from app.routes.notes import router as notes_router
from app.routes.logs import router as logs_router
from app.services.health import HealthMonitor
from app.services.system import SystemMonitor
from app.services.tasks import initialize
from app.services.roadmap import initialize as initialize_roadmap
from app.services.telemetry import monitor_history
from app.services.response_cache import ResponseCache, ResponseHeaders
from app.services.publisher import publisher_lock


@asynccontextmanager
async def lifespan(app):
    with ExitStack() as stack:
        if os.getenv('DASHBOARD_METRICS_MODE', 'host') == 'host':
            stack.enter_context(publisher_lock())
        async with runtime(app):
            yield


@asynccontextmanager
async def runtime(app):
    app.state.health_monitor = HealthMonitor()
    app.state.system_monitor = SystemMonitor()
    tasks = []
    try:
        await asyncio.to_thread(initialize)
        await asyncio.to_thread(initialize_roadmap)
    except (OSError, sqlite3.Error):
        logging.getLogger(__name__).error('Task storage unavailable at startup')
    if os.getenv('DASHBOARD_METRICS_MODE', 'host') == 'host':
        await app.state.system_monitor.sample()
        tasks = [asyncio.create_task(app.state.health_monitor.run()),
                 asyncio.create_task(app.state.system_monitor.run()),
                 asyncio.create_task(monitor_history(app.state))]
    previous_cache = getattr(app.state, 'response_cache', None)
    cache = ResponseCache(app.state)
    app.state.response_cache = cache
    await asyncio.to_thread(cache.refresh)
    tasks.append(asyncio.create_task(cache.run()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if getattr(app.state, 'response_cache', None) is cache:
            if previous_cache is None:
                del app.state.response_cache
            else:
                app.state.response_cache = previous_cache

app = FastAPI(title="adamserv dashboard", version="0.4.0", lifespan=lifespan)
app.include_router(router)
app.include_router(tasks_router)
app.include_router(roadmap_router)
app.include_router(notes_router)
app.include_router(logs_router)


app.add_middleware(ResponseHeaders)


@app.get("/")
async def root():
    return {"name": "adamserv dashboard API", "version": "0.4.0", "docs": "/docs"}
