# Homelab Dashboard

A local control center for Ubuntu homelabs. The dashboard brings host health, service checks, curated logs and project planning into one React interface backed by FastAPI. It is designed to complement existing services, not manage or replace them.

**Supported deployment:** native Ubuntu user services, served on loopback. The project has no authentication; see [Security](docs/security.md) before changing its network exposure.

## What it includes

- **Overview:** CPU, memory, uptime, load, storage, network rates and counters, host status, active alerts, service availability and bounded history.
- **Services:** configured HTTP/TCP and passive local SSH checks with response time, last-success and stale-state information. Checks have strict timeouts and use a local validated catalog.
- **Logs & alerts:** curated dashboard events, bounded journal views, Samba records, filters and CSV export. Log providers use reviewed fixed sources rather than browser-selected commands or paths.
- **Project:** persistent tasks, roadmap items with drag-and-drop ordering, notes and a bounded edit history. Project data is stored in SQLite.
- **Backups:** evidence for the project-database backup and restore-check job. Optional off-host delivery requires separately configured SSH trust and a destination.
- **Appearance and navigation:** light/dark themes, deep links and browser history support; responsive log cards on narrow screens.

The service inventory is configured by the operator. Host monitoring uses a single native API publisher, and project data, local catalogs, backups and generated runtime state stay outside the public repository.

## Architecture

```text
Browser → React/Vite production build served by FastAPI frontend (127.0.0.1:5173)
        → same-origin /api proxy → FastAPI backend (127.0.0.1:8008)
                                  ├─ host/service monitoring
                                  ├─ bounded history and approved log providers
                                  └─ SQLite project data
```

See [Architecture](docs/architecture.md) for sampling, cache, stale-state, performance and memory details. See [Configuration](docs/configuration.md) for catalog fields and environment variables.

## Native Ubuntu setup

Prerequisites are Python 3, Node.js/npm, systemd user services, and the OS libraries/permissions needed for the host metrics and selected log sources. For a fresh checkout at `/srv/homelab/dashboard`:

```bash
cd /srv/homelab/dashboard
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
cp config/catalog.example.json config/catalog.json
cp config/monitoring.env.example config/monitoring.env
cp config/backup.env.example config/backup.env
```

Edit the ignored local catalog with the services and private/loopback probe addresses appropriate to your host. Do not copy the example over an existing catalog or project database: those files may hold host-specific settings and user data. Then build the static frontend, install the provided systemd user units, and enable the services using the [Native deployment guide](docs/native-deployment.md). The included unit files target `/srv/homelab/dashboard`; adjust their paths if your checkout differs.

The app defaults to `http://127.0.0.1:5173`. For remote administration, use an SSH tunnel rather than opening an unauthenticated dashboard to an untrusted network:

```bash
ssh -N -L 5173:127.0.0.1:5173 user@server
```

Then browse to `http://localhost:5173`.

## Local development

Install backend development requirements and frontend dependencies, then run the API and Vite in separate terminals:

```bash
cd /srv/homelab/dashboard/backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8008
```

```bash
cd /srv/homelab/dashboard/frontend
npm ci
npm run dev -- --host 127.0.0.1
```

The Vite proxy targets the local API and preserves the same-origin write protections. The root `.env.example` documents optional variables for manually launched processes; systemd reads the separate files under `config/`.

## Checks

```bash
cd backend && .venv/bin/python -m pytest tests -q
cd ../frontend && npm test && npm run lint && npm run build
```

Optional scripts under `scripts/` cover isolated native candidates, bounded HTTP load, memory profiling, browser workflows and host/log comparisons. Use an isolated database for any browser workflow that creates or edits project data. See [Operations](docs/operations.md).

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Process liveness |
| `GET /api/ready` | Dependency readiness and freshness |
| `GET /api/system` | Host metrics |
| `GET /api/services` | Service check observations |
| `GET /api/catalog` | Validated service configuration and initial seeds |
| `GET /api/history` | Bounded metrics, events and alerts |
| `GET /api/backups` | Backup evidence |
| `GET /api/audit` | Recent project edit history |
| `GET /api/logs/*` | Curated timeline and bounded server/Samba logs |
| `GET`, `POST /api/tasks` | Read or add tasks |
| `PATCH`, `DELETE /api/tasks/{id}` | Edit, complete or remove a task |
| `GET`, `POST /api/roadmap` | Read or add roadmap entries |
| `PATCH`, `DELETE /api/roadmap/{id}` | Edit or remove a roadmap entry |
| `PUT /api/roadmap/order` | Save roadmap ordering |
| `GET`, `PATCH /api/notes` | Read or save Notes to self |

## Repository layout

```text
backend/    FastAPI application, service adapters and tests
frontend/   React/Vite application and frontend tests
config/     Native systemd units and sanitized configuration examples
docs/       Architecture, deployment, configuration, security and operations
scripts/    Useful local verification and profiling tools
data/       Empty runtime-data placeholder; generated data is ignored
```

Only native Ubuntu deployment material is published. Host-specific configuration, secrets, databases, backups, generated builds/reports and container deployment artifacts are excluded from Git.
