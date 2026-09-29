# Native Ubuntu deployment

The supported deployment builds the React/Vite frontend as static assets and runs FastAPI plus a small same-origin static/proxy server as unprivileged systemd user services. No host-wide Nginx or existing ports need to be changed. The unit files in `config/` currently target `/srv/homelab/dashboard`; update those paths consistently if deploying elsewhere.

## Prerequisites and first installation

Install a supported Python 3, Node.js/npm and systemd environment using your OS package-management policy. From the checkout:

```bash
cd /srv/homelab/dashboard
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cp config/catalog.example.json config/catalog.json
cp config/monitoring.env.example config/monitoring.env
cp config/backup.env.example config/backup.env
```

Edit the ignored local catalog to match the host's services before starting. For an existing installation, do not overwrite `config/catalog.json`, `data/tasks/tasks.sqlite3`, notes, audit records or backup data with example files. Catalog task/roadmap values seed only a new project database.

Build a versioned production frontend release and atomically switch the `current` symlink:

```bash
cd /srv/homelab/dashboard
release="production-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "frontend/releases/$release"
(cd frontend && npm ci && npm run build -- --outDir "releases/$release" --emptyOutDir)
ln -sfn "$release" frontend/releases/current.next
mv -Tf frontend/releases/current.next frontend/releases/current
```

Install and enable the provided user units:

```bash
mkdir -p ~/.config/systemd/user
install -m 644 config/adamserv-dashboard-api.service ~/.config/systemd/user/
install -m 644 config/adamserv-dashboard-web.service ~/.config/systemd/user/
install -m 644 config/adamserv-backup.service ~/.config/systemd/user/
install -m 644 config/adamserv-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now adamserv-dashboard-api.service adamserv-dashboard-web.service
systemctl --user enable --now adamserv-backup.timer
```

For unattended startup after logout/reboot, enable user lingering with the administrator-approved command `sudo loginctl enable-linger "$USER"`. The API and frontend have hardening directives and loopback binds; inspect `systemctl --user status` and `/api/ready` before opening the UI. Open `http://127.0.0.1:5173` locally or forward it from a client:

```bash
ssh -N -L 5173:127.0.0.1:5173 user@server
```

## Build and switch updates

Build a new release directory without stopping the currently served version. Inspect the build output, then atomically change `frontend/releases/current` as above. Restart only the API when backend code/configuration changes; restart the frontend unit only when its ASGI server changes. Verify `/api/ready` and the frontend response before considering the update complete.

```bash
systemctl --user restart adamserv-dashboard-api.service
systemctl --user restart adamserv-dashboard-web.service
systemctl --user status adamserv-dashboard-api.service adamserv-dashboard-web.service
curl -fsS http://127.0.0.1:8008/api/health
curl -i http://127.0.0.1:8008/api/ready
curl -I http://127.0.0.1:5173/
```

## Rollback

Keep the previous immutable release directory. To restore it, point `current` at its exact prior release name using a temporary symlink and atomic rename, then restart the web unit. Backend source rollback should use a known-good version-control revision or saved release; preserve the existing database and local config. Do not delete SQLite databases, backups or user-generated project records as part of rollback.

```bash
ln -sfn production-PRIOR_RELEASE frontend/releases/current.rollback
mv -Tf frontend/releases/current.rollback frontend/releases/current
systemctl --user restart adamserv-dashboard-web.service
```

## Disable or remove the services

```bash
systemctl --user disable --now adamserv-backup.timer
systemctl --user disable --now adamserv-dashboard-web.service adamserv-dashboard-api.service
```

Removing service units does not remove application data. Back up and deliberately handle `data/` separately if uninstalling.
