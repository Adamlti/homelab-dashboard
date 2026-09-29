import { useEffect, useState } from 'react'
import { serviceState } from '../serviceState'

export function Attention({ history, historyError, catalog, services, servicesError }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const results = new Map((services?.services || []).map(row => [row.id, row]))
  const names = new Map((catalog?.services || []).map(row => [row.id, row.name]))
  const affected = (catalog?.services || []).map(service => ({ ...service,
    state: serviceState(results.get(service.id), service.check, servicesError, now, services?.stale_after_seconds),
  })).filter(service => !['online', 'not_configured'].includes(service.state.status))
  const age = (now - Date.parse(history?.sampled_at)) / 1000
  const stale = !!historyError || history?.stale || !Number.isFinite(age) || age > 30 || age < -5
  const alerts = (history?.alerts || []).filter(alert => !affected.some(service => service.id === alert.subject.replace(/^service:/, '')))
  const attention = affected.length || alerts.length || stale || servicesError
  return <section className={`overview-attention ${attention ? 'needs-attention' : ''}`} aria-labelledby="attention-title">
    <div className="row"><h2 id="attention-title">{attention ? 'Needs attention' : 'No active alerts'}</h2><a href="#/logs/general">Alerts & history →</a></div>
    {affected.length > 0 && <ul className="attention-services">{affected.map(service => <li key={service.id}><a href="#/services"><strong>{service.name}</strong> · {service.state.label}</a></li>)}</ul>}
    {alerts.length > 0 && <ul>{alerts.map(alert => <li key={alert.subject}><strong>{names.get(alert.subject) || alert.subject}</strong> · {alert.detail}</li>)}</ul>}
    {(stale || servicesError) && <p>Monitoring observations are unavailable or stale; retained results do not confirm current health.</p>}
    {!attention && <p>Configured services have current checks. Host availability is shown separately below.</p>}
  </section>
}
