import { useEffect, useState } from 'react'
import { Panel } from './Overview'
import { chartSegments } from '../historyChart'

export function History({ history, error }) {
  const [hours, setHours] = useState('24')
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const age = history ? (now - Date.parse(history.sampled_at)) / 1000 : Infinity
  const stale = !!error || history?.stale || age > 30 || age < -5
  const points = (history?.points || []).filter(point => now - Date.parse(point.at) <= Number(hours) * 3600000)
  return <>
    <Panel title="Resource history" subtitle="One observation per minute · Up to 72 hours" aside={<label className="log-search">History range<select value={hours} onChange={event => setHours(event.target.value)}><option value="1">Last hour</option><option value="6">Last 6 hours</option><option value="24">Last 24 hours</option><option value="72">Last 72 hours</option></select></label>}>
      {(error || (history && stale)) && <p className="notice" role="alert">{error || 'History publication is stale.'} Charts show previous observations.</p>}
      {!history && !error && <p className="empty">Waiting for monitoring history…</p>}
      {history && !points.length && <p className="empty">No resource history yet. Samples appear as the collector observes the host.</p>}
      {!!points.length && <div className="history-grid">{[['cpu', 'CPU'], ['memory', 'Memory'], ['disk', 'Highest disk usage']].map(([metric, label]) => {
        const latest = points.at(-1)[metric]
        const previous = points.at(-2)?.[metric]
        const continuous = points.length > 1 && Date.parse(points.at(-1).at) - Date.parse(points.at(-2).at) <= 120000
        const change = continuous && latest != null && previous != null ? latest - previous : null
        return <figure className="history-chart" key={metric}>
          <figcaption>{label}<strong>{latest == null ? '—' : `${latest.toFixed(1)}%`}</strong></figcaption>
          <p className="check-detail">{change == null ? 'Trend unavailable' : `${change > 0 ? '↑' : change < 0 ? '↓' : '→'} ${Math.abs(change).toFixed(1)} percentage points since previous sample`}</p>
          <svg viewBox="0 -3 300 106" role="img" aria-label={`${label}, 0 to 100 percent. Gaps indicate unavailable observations.`}>
            <path className="chart-guide" d="M0 0H300 M0 50H300 M0 100H300" />
            {chartSegments(points, metric).map((segment, index) => segment.length === 1 ? <circle key={index} cx={segment[0][0]} cy={segment[0][1]} r="2" /> : <polyline key={index} points={segment.map(point => point.join(',')).join(' ')} fill="none" strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
          </svg>
          <div className="chart-times"><time dateTime={points[0].at}>{new Date(points[0].at).toLocaleString()}</time><time dateTime={points.at(-1).at}>{new Date(points.at(-1).at).toLocaleString()}</time></div>
        </figure>
      })}</div>}
      <p className="panel-footnote">Lines break across sampling gaps. Current alerts and alert history are available in Logs.</p>
    </Panel>
  </>
}
