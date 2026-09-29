# Operations

## Install and start

Follow [Native deployment](native-deployment.md). The provided systemd user units assume this checkout is at `/srv/homelab/dashboard`, the Python virtual environment is at `backend/.venv`, and dependencies have already been installed. Adjust their absolute paths if you clone elsewhere. The web/API services bind to loopback ports 5173 and 8008; use an SSH tunnel or configured LAN reverse proxy only after reviewing the security model.

## Service commands

```bash
systemctl --user status adamserv-dashboard-api.service adamserv-dashboard-web.service
systemctl --user restart adamserv-dashboard-api.service adamserv-dashboard-web.service
journalctl --user -u adamserv-dashboard-api.service -n 100 --no-pager
journalctl --user -u adamserv-dashboard-web.service -n 100 --no-pager
curl -fsS http://127.0.0.1:8008/api/health
curl -i http://127.0.0.1:8008/api/ready
curl -I http://127.0.0.1:5173/
```

A readiness `503` includes dependency details and can indicate stale host/service observations or an unreadable catalog/database. Individual monitored services can be offline while the dashboard itself is live. Check `systemctl --user list-timers adamserv-backup.timer` for the daily backup timer; run `systemctl --user start adamserv-backup.service` for an operator-requested backup and inspect its journal/status artifact.

## Logs and retention

General events are curated state transitions, resource alerts, boot information and project edits; they are not an unrestricted host-log browser. Server log views use bounded journal queries and expose selected journal fields; numeric journal priority remains available as diagnostic information. Samba combines a bounded `smbd.service` journal view with the tail of the fixed `/var/log/samba/log.smbd` file. The file view returns at most 800 lines from the current file, excludes rotated files, and has no separate age cutoff; Samba/Ubuntu log rotation controls the file's age. The journal view uses its own seven-day window. Secret-like values are redacted.

Local automatic project backups retain the most recent 30 scheduled artifacts after a successful restore check. Manual backups are not pruned. Off-host delivery is optional and not configured by the template; remote retention must be configured independently. A backup is not a full-server image.

## Safe development and checks

Use a disposable checkout and database for browser tests that perform task/roadmap writes. `scripts/native_candidate.py` runs the built frontend/API against isolated temporary state and alternate loopback ports. `scripts/profile_monitoring.py` and `scripts/benchmark.py` help compare bounded performance/memory behavior. See [Native deployment](native-deployment.md) for production-build update and rollback commands. Do not run write-oriented browser tests against the real project database.
