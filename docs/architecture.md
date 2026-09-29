# Architecture

The dashboard is a same-origin React single-page application backed by FastAPI. In the native deployment, one unprivileged FastAPI process samples the host and configured services, publishes bounded snapshots/history, and serves the API. A separate unprivileged ASGI frontend process serves an immutable Vite production build and proxies only `/api/*` to the API over loopback. Both listeners default to loopback. The browser never receives host credentials or direct access to system APIs.

```text
Browser → native frontend (127.0.0.1:5173)
        → same-origin /api proxy → FastAPI (127.0.0.1:8008)
                                  ├─ background host sampler
                                  ├─ bounded HTTP/TCP/passive SSH checks
                                  ├─ allowlisted log providers
                                  ├─ metrics history and alert transitions
                                  └─ SQLite project data
```

FastAPI is the single native host/service publisher. Host metrics refresh on a background interval, service checks and history are published periodically, and stale snapshots fail visibly instead of appearing current. The request path does not synchronously sample CPU. Monitoring responses use a bounded background cache with expiry and reuse serialized bytes when data has not changed. Project reads and writes bypass that cache. HTTP clients are reused and closed during process shutdown. Do not run a second publisher against the same history file.

Readiness distinguishes application liveness from usable dependencies: `/api/health` reports process liveness; `/api/ready` verifies catalog, SQLite and monitoring freshness. An offline service does not by itself mean the dashboard API is unhealthy. Probe timeouts are bounded; HTTP probes do not follow redirects or use ambient proxy settings. Catalog probe targets must be explicit private/loopback addresses. SSH monitoring is passive: fixed local systemd state plus listener metadata, with no SSH connection or authentication attempt.

The response cache retains a previous payload for endpoint-specific stale behavior and keeps source freshness/last-success timestamps. Monitoring samples include CPU, memory, uptime, load, storage and network; interface throughput is a delta between samples, while error/drop counts are cumulative since boot. Resource history is bounded to 4,320 minute observations; event and alert lists retain their latest 100 entries. Log providers use bounded fixed sources and redact secret-like values.

## Performance and memory evidence

The native implementation moved CPU sampling off the request path, serializes monitoring responses in the background, reuses HTTP clients, and caches parsed history by file version. A bounded native production burst of 400 read requests at concurrency 100 completed with no errors and approximately 209 ms p95; five follow-up bursts measured approximately 202–227 ms p95. These are local snapshots, not a sustained-capacity guarantee.

A fresh-process profiling comparison over 120 accelerated health cycles measured about 21.4 MiB RSS growth with fresh clients and 1.4 MiB with a reused client after warm-up. This identified client/request churn as a retained-memory contributor. It did not explain every earlier high-water mark or establish multi-day leak freedom. `scripts/profile_monitoring.py` records RSS, Python allocations, descriptors and threads and has a configurable post-warm-up growth budget for repeatable regression checks.

## Project data

Tasks, roadmap ordering, notes and edit audit history live in SQLite. Project writes use transactions and same-origin request protections. Catalog `roadmap` and `tasks` entries seed a fresh database only; editing the catalog does not overwrite saved user data. Keep live catalogs and SQLite files outside version control.
