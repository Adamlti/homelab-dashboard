import { useEffect, useState } from 'react'
import { Panel } from './Overview'
import { serviceState } from '../serviceState'

export function Services({ catalog, health, error, compact = false, onOpen }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    // Results must expire even when API polling stops succeeding.
    const timer = setInterval(() => setNow(Date.now()), 1000)
  return () => clearInterval(timer)
  }, [])
  const results = new Map(health?.services.map(result => [result.id, result]) || [])
    if (compact) return <Panel title="Services at a glance" subtitle="Latest reachability" aside={<button className="text-button" onClick={onOpen}>View all services →</button>}>
    {error && <p className="notice" role="alert">{error}</p>}
    <div className="service-summary">{catalog?.services.map(service => {
      const state = serviceState(results.get(service.id), !!service.check, !!error, now, health?.stale_after_seconds)
      if (!service.check && !service.url) return <div key={service.id} className="service-summary-item"><strong>{service.name}</strong><span className="service-status not_configured">Not connected</span></div>
      return <button key={service.id} className="service-summary-item" onClick={onOpen} aria-label={`View ${service.name} details`}><strong>{service.name}</strong><span className={`service-status ${state.status}`}>{state.status === 'online' && service.check?.type === 'tcp' ? 'Port reachable' : state.label}</span></button>
    }) || <p className="empty">Loading services…</p>}</div>
  </Panel>
  return (
    <Panel title="Services" subtitle="HTTP, SSH and TCP checks" aside={<span className="tag">READ-ONLY CHECKS</span>}>
      {error && <p className="notice" role="alert">{error}</p>}
      <div className="services-grid">
        {catalog?.services.map(service => {
          const result = results.get(service.id)
          const state = serviceState(result, !!service.check, !!error, now, health?.stale_after_seconds)
          return (
            <article className="service" key={service.id}>
              <div className="service-icon" aria-hidden="true">{service.name.slice(0, 1)}</div>
              <div className="service-info">
                <h3>{service.name}</h3>
                <p>{service.description}</p>
                <span className={`service-status ${state.status}`} role="status">{state.status === 'online' && service.check?.type === 'tcp' ? 'Port reachable' : state.label}</span>
                {service.check && <p className="check-detail">{service.check.type.toUpperCase()} · {service.check.timeout_seconds ?? 2}s timeout{result?.latency_ms != null && ` · ${Math.round(result.latency_ms)} ms`}</p>}
                {result && <p className="check-detail">{result.detail}</p>}
                {service.link_warning && <p className="check-detail warning-text">{service.link_warning}</p>}
                {result?.checked_at && <p className="check-detail">Checked {Math.max(0, Math.floor((now - Date.parse(result.checked_at)) / 1000))}s ago · <time dateTime={result.checked_at}>{new Date(result.checked_at).toLocaleTimeString()}</time></p>}
                {service.check && <p className="check-detail">Last success: {result?.last_success_at ? <time dateTime={result.last_success_at}>{new Date(result.last_success_at).toLocaleString()}</time> : 'No recorded success'}</p>}
              </div>
              {!service.link_warning && /^https?:\/\//.test(service.url || '') && <a className="service-link" href={service.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${service.name}`}>↗</a>}
            </article>
          )
        }) || <p className="empty">Loading service catalog…</p>}
      </div>
      <p className="panel-footnote">TCP checks confirm an open port. HTTP checks confirm an expected response status. Local SSH checks inspect unit readiness and a listening socket without opening a connection; login and remote reachability are not tested. Results expire after 30 seconds; Docker monitoring is not connected.</p>
    </Panel>
  )
}
