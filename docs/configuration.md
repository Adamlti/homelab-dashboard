# Configuration

## First-run files

Copy the public templates and edit them for the machine where the dashboard will run:

```bash
cp config/catalog.example.json config/catalog.json
cp config/monitoring.env.example config/monitoring.env
cp config/backup.env.example config/backup.env
```

`config/catalog.json` is deliberately ignored because it contains machine-specific service names, links, probe addresses, roadmap entries and task seeds. The checked-in `catalog.example.json` contains only loopback examples and empty project seeds. Replace URLs and checks with literal private/loopback addresses appropriate to your own host. Never add credentials or public probe targets. A service may have a `null` check to show that monitoring is not configured.

The systemd API unit reads the optional `config/monitoring.env`; the backup unit reads optional `config/backup.env`. The root `.env.example` documents equivalent optional variables for a manually launched API and is not automatically loaded by systemd. After changing alert thresholds, restart the API unit.

## Environment variables

| Variable | Purpose | Default/constraints |
| --- | --- | --- |
| `DASHBOARD_METRICS_MODE` | Native host sampler mode | `host` |
| `DASHBOARD_ALERT_CPU` | CPU alert threshold, percent | 90; greater than 0 and at most 100 |
| `DASHBOARD_ALERT_MEMORY` | Memory alert threshold, percent | 90; greater than 0 and at most 100 |
| `DASHBOARD_ALERT_STORAGE` | Storage alert threshold, percent | 85; greater than 0 and at most 100 |
| `DASHBOARD_DISK_PATHS` | Colon-separated mounts to sample | `/` |
| `DASHBOARD_NETWORK_INTERFACES` | Comma-separated interfaces to sample | automatic selection |
| `DASHBOARD_CATALOG_PATH` | Service/seed catalog path | `config/catalog.json` |
| `DASHBOARD_TASKS_PATH` | SQLite project database path | `data/tasks/tasks.sqlite3` |
| `DASHBOARD_HISTORY_PATH` | Native metrics history path | `data/native/history.json` |
| `DASHBOARD_BACKUP_STATUS_PATH` | Published backup status path | `data/backups/latest-backup.json` |

Other snapshot, lock and frontend-build overrides exist for isolated development/verification; inspect the application defaults before using them in a service unit. Avoid running multiple publishers against one history file.

## Backup settings

`DASHBOARD_BACKUP_OFFHOST` accepts an existing SSH destination in `user@host:/absolute/directory` form. SSH trust and keys belong in the operator's SSH configuration, not the repository. Off-host retention is the receiving system's responsibility. The local scheduled job covers only the project SQLite database, validates a copy by restoring/checking it, and retains the latest 30 of its own scheduled backups. It does not back up media, Samba shares, or other service configuration.
