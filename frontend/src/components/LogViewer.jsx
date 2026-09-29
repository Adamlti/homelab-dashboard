import { useEffect, useState } from 'react'
import { downloadLogs } from '../logsCsv'
import { buildLogUrl } from '../logApi'
import { Panel } from './Overview'

async function getLogs(url, signal) {
  const response = await fetch(url, { signal, cache: 'no-store' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Log source request failed (${response.status})`)
  }
  return response.json()
}

export function LogViewer({ provider, title, description, categories = [], refreshToken = 0 }) {
  const [category, setCategory] = useState(categories[0]?.value || '')
  const [severity, setSeverity] = useState('all')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [limit, setLimit] = useState(50)
  const [reload, setReload] = useState(0)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loadedKey, setLoadedKey] = useState(null)
  const url = buildLogUrl(provider, category, severity, appliedSearch, limit)
  const requestKey = JSON.stringify([url, refreshToken, reload])
  const loading = loadedKey !== requestKey

  useEffect(() => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10000)
    let current = true
    getLogs(url, controller.signal)
      .then(result => { if (current) { setData(result); setError(null) } })
      .catch(reason => { if (current) setError(reason.name === 'AbortError' ? 'The log source timed out before returning a bounded response.' : reason.message) })
      .finally(() => { clearTimeout(timeout); if (current) setLoadedKey(requestKey) })
    return () => { current = false; clearTimeout(timeout); controller.abort() }
  }, [url, requestKey])

  const rows = data?.entries || []
  const applySearch = event => { event.preventDefault(); setAppliedSearch(search); setReload(value => value + 1) }
  const clearFilters = () => {
    setSearch('')
    setAppliedSearch('')
    setSeverity('all')
    setCategory(categories[0]?.value || '')
    setLimit(50)
    setReload(value => value + 1)
  }
  const exportRows = rows.map(row => ({ at: row.timestamp, name: `${row.severity.toUpperCase()} · ${row.source}`, detail: row.message }))

  return <Panel title={title} subtitle={description} aside={<button className="refresh" disabled={!rows.length} onClick={() => downloadLogs(exportRows, `${provider}-logs`)}>Download CSV</button>}>
    {categories.length > 1 && <div className="log-filters log-category-filters" role="group" aria-label="Log category">
      {categories.map(option => <button type="button" key={option.value} className={category === option.value ? 'selected' : ''} aria-pressed={category === option.value} onClick={() => { setCategory(option.value); setReload(value => value + 1) }}>{option.label}</button>)}
    </div>}
    <form className="log-viewer-controls" onSubmit={applySearch}>
      <label>Severity<select id={`${provider}-log-severity`} value={severity} onChange={event => setSeverity(event.target.value)}><option value="all">All severities</option><option value="error">Error</option><option value="warning">Warning</option><option value="info">Info</option></select></label>
      <label className="log-viewer-search">Search<input type="search" value={search} maxLength="120" onChange={event => setSearch(event.target.value)} placeholder="Source or message" /></label>
      <label>Result limit<select id={`${provider}-log-limit`} value={limit} onChange={event => setLimit(Number(event.target.value))}><option value="25">25</option><option value="50">50</option><option value="100">100</option><option value="200">200</option></select></label>
      <button className="refresh" type="submit">Apply search</button>
      <button className="refresh" type="button" onClick={() => setReload(value => value + 1)} disabled={loading}>{loading ? 'Refreshing…' : '↻ Refresh logs'}</button>
      <button className="refresh" type="button" onClick={clearFilters}>Clear filters</button>
    </form>
    {error && <p className="notice" role="alert">{error}{data ? ' Previously loaded results remain below and may be stale.' : ''}</p>}
    {loading && <p className="panel-footnote" role="status">Loading the selected view… Previous results may remain until it finishes.</p>}
    <div className="logs-table-wrap desktop-log-table">
      <table className="logs-table provider-logs-table">
        <caption className="sr-only">{title}</caption>
        <thead><tr><th scope="col">Timestamp</th><th scope="col">Severity</th><th scope="col">Source</th><th scope="col">Message</th></tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row.timestamp}-${row.source}-${index}`}><td><time dateTime={row.timestamp}>{new Date(row.timestamp).toLocaleString()}</time></td><td><span className={`severity-badge severity-${row.severity}`}>{row.severity}</span>{row.journal_priority != null && <small className="journal-priority">Journal priority {row.journal_priority}</small>}</td><td>{row.source}</td><td>{row.message}</td></tr>)}</tbody>
      </table>
    </div>
    <ul className="mobile-log-cards" aria-label={title}>{rows.map((row, index) => <li key={`${row.timestamp}-${row.source}-${index}`}>
      <div className="log-card-meta"><time dateTime={row.timestamp}>{new Date(row.timestamp).toLocaleString()}</time><span className={`severity-badge severity-${row.severity}`}>{row.severity}</span></div>
      <strong className="log-card-source">{row.source}</strong><p>{row.message}</p>
      {row.journal_priority != null && <small className="journal-priority">Journal priority {row.journal_priority}</small>}
    </li>)}</ul>
    {!rows.length && <p className="empty logs-empty">{loading && !data ? 'Loading bounded log results…' : error && !data ? 'No retained log results are available.' : appliedSearch ? 'No entries match the current search and filters.' : 'No real events were found for this source and filter.'}</p>}
    <p className="panel-footnote">{data ? `${data.returned} of at most ${data.limit} results · Generated ${new Date(data.generated_at).toLocaleString()}. ` : ''}{data?.detail} {data?.sources?.length ? `Sources: ${data.sources.join(' · ')}.` : ''}</p>
  </Panel>
}
