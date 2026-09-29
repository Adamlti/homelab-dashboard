export function MetricCard({ label, value, detail, percent }) {
  return <article className="metric-card"><h2>{label}</h2><strong className="metric-value">{value}</strong><p>{detail}</p>{percent != null ? <progress max="100" value={percent} aria-label={label} /> : <div className="uptime-line" />}</article>
}
export function Panel({ title, subtitle, aside, className = '', children }) {
  return <section className={`panel ${className}`.trim()}><div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{aside}</div>{children}</section>
}
