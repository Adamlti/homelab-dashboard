from .common import filter_entries, journal_entries, response


CATEGORY_ARGUMENTS = {
    'all': ['--since=-24h'],
    'errors': ['--since=-7d', '--priority=err..emerg'],
    'warnings': ['--since=-7d', '--priority=warning..emerg'],
    'current_boot': ['--boot=0'],
    'kernel': ['--boot=0', '--dmesg'],
}


def get_logs(category='all', severity='all', search='', limit=50):
    scan_limit = min(800, max(100, limit * 4))
    if category == 'authentication':
        entries = journal_entries(['--boot=0', '--unit=ssh.service', '--unit=sshd.service'], scan_limit, 'SSH')
        entries += journal_entries(['--boot=0', '_COMM=sudo'], scan_limit, 'sudo')
        sources = ['systemd journal: ssh.service/sshd.service', 'systemd journal: sudo process records']
        detail = 'Authentication activity from the current boot; no authentication files are read directly.'
    else:
        entries = journal_entries(CATEGORY_ARGUMENTS[category], scan_limit, 'systemd')
        if category == 'warnings':
            # Include promoted kernel denials even if journald classified them as info.
            denials = journal_entries(
                ['--since=-7d', '_TRANSPORT=kernel', '--grep=apparmor="DENIED"'],
                scan_limit, 'kernel')
            seen = {(entry.timestamp, entry.source, entry.message) for entry in entries}
            entries += [entry for entry in denials if entry.severity in ('warning', 'error')
                        and (entry.timestamp, entry.source, entry.message) not in seen]
        sources = ['systemd journal (structured JSON fields)']
        detail = {
            'all': 'Recent server journal entries from the last 24 hours.',
            'errors': 'Journal priorities error through emergency from the last seven days.',
            'warnings': 'Journal warnings/errors plus AppArmor denials from the last seven days; raw priority is retained.',
            'current_boot': 'All journal entries since the current boot, including ongoing activity; not just startup events.',
            'kernel': 'Kernel journal entries associated with the current boot.',
        }[category]
    entries = filter_entries(entries, severity, search, limit)
    return response('server', entries, limit, sources, detail)
