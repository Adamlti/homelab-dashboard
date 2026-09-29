import { Panel } from './Overview'
import { formatBytes } from '../format'

export function Backups({ status }) {
  return <Panel title="Project backup" subtitle="Tasks and roadmap · Local SQLite copy">
    <p className={status?.status === 'current' ? 'online-text' : 'warning-text'} role="status">{status?.detail || 'Backup status unavailable'}</p>
    {status?.last_success && <dl className="details backup-details"><div><dt>Last verified backup</dt><dd><time dateTime={status.last_success.completed_at}>{new Date(status.last_success.completed_at).toLocaleString()}</time></dd></div><div><dt>File</dt><dd>{status.last_success.filename}</dd></div><div><dt>Size</dt><dd>{formatBytes(status.last_success.size_bytes)}</dd></div><div><dt>Restore check</dt><dd>{status.last_success.restore_checked_at ? new Date(status.last_success.restore_checked_at).toLocaleString() : 'Not recorded'}</dd></div><div><dt>Off-host copy</dt><dd>{status.last_success.offhost_verified_at ? `Checksum verified ${new Date(status.last_success.offhost_verified_at).toLocaleString()}` : 'Not configured / not verified'}</dd></div></dl>}
    <p className="panel-footnote">Scheduled project backups include an isolated restore and row comparison. Current status checks file size and modification time; verification dates describe completed checks. These backups cover dashboard tasks and roadmap only.</p>
  </Panel>
}
