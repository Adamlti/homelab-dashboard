import { useEffect, useState } from 'react'
import { LogViewer } from './LogViewer'
import { Panel } from './Overview'

const pages = {
  LogsGeneral: {
    provider: 'general',
    title: 'General events',
    description: 'Curated dashboard events, alert transitions, and project edits',
    categories: [
      { value: 'timeline', label: 'Timeline' },
      { value: 'alerts', label: 'Alert history' },
      { value: 'project', label: 'Project edits' },
    ],
  },
  LogsServer: {
    provider: 'server',
    title: 'Server logs',
    description: 'Bounded Ubuntu journal records from approved server sources',
    categories: [
      { value: 'all', label: 'All' },
      { value: 'errors', label: 'Errors' },
      { value: 'warnings', label: 'Warnings' },
      { value: 'current_boot', label: 'Current boot' },
      { value: 'kernel', label: 'Kernel' },
      { value: 'authentication', label: 'Authentication' },
    ],
  },
  LogsSamba: {
    provider: 'samba',
    title: 'Samba logs',
    description: 'Recent smbd journal and approved Samba file records',
    categories: [
      { value: 'operational', label: 'Operational' },
      { value: 'all', label: 'All' },
    ],
  },
}

function CurrentAlerts({ history, error, catalog }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const age = history ? (now - Date.parse(history.sampled_at)) / 1000 : Infinity
  const stale = !!error || history?.stale || age > 30 || age < -5
  const names = new Map((catalog?.services || []).map(service => [service.id, service.name]))
  const name = subject => names.get(subject.replace(/^service:/, '')) || ({ system: 'System', 'service checks': 'Service checks' }[subject] ?? subject)
  return <>
    {(error || (history && stale)) && <p className="notice" role="alert">{error || 'Monitoring history is stale.'} The last observed alert state is retained below.</p>}
    <Panel title={stale ? 'Last observed alerts' : 'Current alerts'} subtitle="Resource thresholds and service checks">
      {history?.alerts.length ? <ul className="current-alerts">{history.alerts.map(alert => <li key={alert.subject}><strong>{name(alert.subject)}</strong><span>{alert.detail}</span></li>)}</ul> : <p className="empty">{!history ? 'Waiting for alert observations…' : stale ? 'No alerts in the last observation.' : 'No active alerts.'}</p>}
    </Panel>
  </>
}

export function Logs({ section, history, historyError, catalog, refreshToken }) {
  const page = pages[section] || pages.LogsGeneral
  return <>
    {section === 'LogsGeneral' && <CurrentAlerts history={history} error={historyError} catalog={catalog} />}
    <LogViewer key={section} {...page} refreshToken={refreshToken} />
  </>
}
