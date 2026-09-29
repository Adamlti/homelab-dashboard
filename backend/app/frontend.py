"""Native production static frontend and fixed loopback API proxy. No dev runtime."""
from contextlib import asynccontextmanager
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles

SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}
MAX_BODY = 65536
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade'}


def forward_headers(headers):
    excluded = HOP_HEADERS | {value.strip().lower() for value in headers.get('connection', '').split(',')}
    # Preserve the browser's Host and Origin; never trust incoming forwarded identity.
    return {key: value for key, value in headers.items()
            if key.lower() not in excluded and not key.lower().startswith(('x-forwarded-', 'forwarded'))}


@asynccontextmanager
async def lifespan(app):
    port = int(os.getenv('DASHBOARD_API_PORT', '8008'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid loopback API port')
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                                 follow_redirects=False, timeout=12,
                                 limits=httpx.Limits(max_connections=64, max_keepalive_connections=16)) as client:
        app.state.client = client
        yield


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                replaced = {key.lower().encode() for key in SECURITY_HEADERS} | {b'cache-control'}
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() not in replaced]
                message['headers'] = headers + [(k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items()] + [(b'cache-control', b'no-store')]
            await send(message)
        await self.app(scope, receive, secured)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityHeaders)


@app.api_route('/api/{path:path}', methods=['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'])
async def api_proxy(request: Request, path: str):
    if request.method not in ('GET', 'HEAD') and path.split('/')[0] not in ('tasks', 'roadmap', 'notes'):
        return JSONResponse({'detail': 'Monitoring endpoints are read-only'}, status_code=405)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            return JSONResponse({'detail': 'Project request exceeds 64 KiB'}, status_code=413)
    try:
        # raw_path preserves escaping. The destination host/port is operator-fixed.
        target = request.scope['raw_path'].decode('ascii')
        if request.url.query:
            target += '?' + request.url.query
        result = await request.app.state.client.request(request.method, target,
                    headers=forward_headers(request.headers), content=bytes(body))
    except httpx.HTTPError:
        return JSONResponse({'detail': 'Dashboard API unavailable; retry after checking the native API service'}, status_code=502)
    headers = forward_headers(result.headers)
    # HTTPX decoded the body already; do not forward its compressed length/encoding.
    for name in ('content-length', 'content-encoding'):
        headers.pop(name, None)
    return Response(result.content, status_code=result.status_code, headers=headers)


app.mount('/', StaticFiles(directory=os.getenv('DASHBOARD_FRONTEND_DIST', str(
    Path(__file__).resolve().parents[2] / 'frontend/dist')), html=True, check_dir=False), name='frontend')
