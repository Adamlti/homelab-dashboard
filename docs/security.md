# Security model

The dashboard is intentionally a local, primarily read-only control center. It has **no authentication**. Anyone who can reach it can read monitoring/log data and edit project tasks, roadmap and notes. The supported default binds frontend/API listeners to loopback; use an SSH tunnel or a deliberately controlled trusted LAN. Do not expose it to the internet. Loopback binding and same-origin write checks are not user authentication or authorization.

The native systemd processes run as the invoking unprivileged user. The units enable `NoNewPrivileges`, private temporary directories/user namespaces, a read-only system view and restricted writable paths where compatible. The API writes only to its project data area. Do not run it as root, grant broad capabilities, or mount privileged host paths and host interfaces.

Project writes require JSON, an application request marker, and matching Host/Origin checks. CORS is not enabled. The frontend proxy preserves the original Host/Origin and does not trust forwarded identity headers. Responses include a same-origin Content Security Policy and browser security headers. These measures reduce cross-origin/drive-by writes; they do not prevent an authorized network user from editing data.

Probe destinations are fixed in a validated local catalog: literal private/loopback addresses, bounded timeouts, no redirects, and no proxy-environment routing. Log readers use fixed journal queries and an allowlisted Samba log file; they do not accept caller-selected commands, paths or shell expressions. Secret-like values are redacted. SSH status checks do not attempt login or create authentication events.

Backups can contain personal project data. Runtime databases, backups, host-specific catalogs, environment files, logs, private keys, certificates and generated reports are excluded from Git. Keep local data and off-host destinations access-controlled, and test restoration before relying on a backup.
