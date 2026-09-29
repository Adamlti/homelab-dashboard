import { useState } from 'react'
import { isLogWorkspace, useWorkspace, workspaceLabel } from './hooks/useWorkspace'
import { Services } from './components/Services'
import { Project } from './components/Project'
import { History } from './components/History'
import { Logs } from './components/Logs'
import { SidebarNavigation } from './components/SidebarNavigation'
import { applyTheme, storedTheme } from './theme'
import { Backups } from './components/Backups'
import { Attention } from './components/Attention'
import { useDashboard } from './hooks/useDashboard'
import { MetricCard, Panel } from './components/Overview'
import { formatBytes, formatUptime } from './format'
import './App.css'


export default function App() {
  const [section, setSection] = useWorkspace()
  const [theme, setTheme] = useState(storedTheme)
  const toggleTheme = () => { const next = theme === 'dark' ? 'light' : 'dark'; applyTheme(next); setTheme(next) }
  const { system, catalog, services, servicesError, error, catalogError, apiOnline, loading, refresh, refreshToken, readiness, history, historyError, backups } = useDashboard()
  const healthy = !!system && !error
  const status = loading && !system ? 'Connecting' : healthy ? 'Server online' : apiOnline ? 'Metrics unavailable' : 'API unreachable'
  const label = workspaceLabel(section)
  const logSection = isLogWorkspace(section)
  const heading = section === 'Overview' ? 'Your server, at a glance.' : section === 'Services' ? 'One home for your services.' : logSection ? `${label} logs and alerts.` : 'Build the next chapter.'
  const description = section === 'Overview' ? 'Live system information from your homelab.' : section === 'Services' ? 'Open existing tools and track monitoring readiness.' : logSection ? 'Read-only, bounded records from approved local sources.' : 'A small, deliberate roadmap for your homelab.'
  return <div className="app-shell">
    <aside className="sidebar">
      <a href="#/overview" className="brand"><span className="brand-icon">a</span><span>adamserv<small>HOMELAB CONTROL CENTER</small></span></a>
      <p className="nav-label">WORKSPACE</p>
      <SidebarNavigation section={section} />
      <div className="sidebar-note">● Host monitoring · V1<p>Local visibility.<br />Your services stay in control.</p></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><span>Homelab <span className="muted">/ {logSection ? `Logs / Alerts / ${label}` : label}</span></span><div className="topbar-actions"><span className="tag">LOCAL ACCESS</span><button className="refresh theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>{theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'}</button></div></header>
      <main id="main">
        <div className="page-heading"><div><p className="eyebrow">ADAMSERV / {logSection ? `LOGS / ${label.toUpperCase()}` : label.toUpperCase()}</p><h1>{heading}</h1><p className="muted">{description}</p></div><button className="refresh" onClick={refresh} disabled={loading}>{loading ? 'Refreshing…' : '↻ Refresh'}</button></div>
        {section === 'Overview' && <Attention history={history} historyError={historyError} catalog={catalog} services={services} servicesError={servicesError} />}
        <div className="server-strip"><div><span className={`status-dot ${healthy ? 'online' : 'warning'}`} /><strong>{system?.hostname || 'adamserv'}</strong><span className="muted">{system?.os || 'Waiting for host metrics'} · Host availability only</span></div><span className={healthy ? 'status online-text' : 'status warning-text'} role="status">{status}</span></div>
        {error && <div className="notice" role="alert">{error}{system && ' Last successful values remain below; they are stale.'}</div>}
        {readiness?.status === 'not_ready' && <div className="notice" role="alert">Dashboard dependencies unhealthy: {Object.entries(readiness.dependencies).filter(([, value]) => value.status === 'unhealthy').map(([name, value]) => `${name}: ${value.detail}`).join(' · ')}</div>}
        {system?.warnings.map(warning => <div key={warning} className="notice">{warning}</div>)}
        {catalogError && <div className="notice" role="alert">{catalogError}</div>}
        {section === 'Overview' && <>
          <div className="metrics-grid">
            <MetricCard label="CPU USAGE" value={system ? `${system.cpu_percent.toFixed(1)}%` : '—'} detail={system ? `${system.cpu_count} logical cores` : 'Awaiting sample'} percent={system?.cpu_percent} />
            <MetricCard label="MEMORY" value={system ? formatBytes(system.memory.used) : '—'} detail={system ? `of ${formatBytes(system.memory.total)} · ${system.memory.percent}% used` : 'Awaiting sample'} percent={system?.memory.percent} />
            <MetricCard label="MAIN STORAGE" value={system?.disks[0] ? formatBytes(system.disks[0].used) : '—'} detail={system?.disks[0] ? `of ${formatBytes(system.disks[0].total)} · ${system.disks[0].percent}% used` : 'No storage sample'} percent={system?.disks[0]?.percent} />
            <MetricCard label="UPTIME" value={system ? formatUptime(system.uptime_seconds) : '—'} detail="Since the host last booted" />
          </div>
          <div className="details-grid">
            <Panel title="System details" subtitle="Host resources"><dl className="details"><div><dt>Hostname</dt><dd>{system?.hostname || '—'}</dd></div><div><dt>Operating system</dt><dd>{system?.os || '—'}</dd></div><div><dt>Kernel</dt><dd>{system?.kernel || '—'}</dd></div><div><dt>Load · 1 / 5 / 15 min</dt><dd>{system?.load_average.map(n => n.toFixed(2)).join(' / ') || '—'}</dd></div></dl></Panel>
            <Panel title="Storage" subtitle="Configured host paths">{system?.disks.length ? system.disks.map(disk => <div className="storage-row" key={disk.path}><div className="row"><strong>{disk.path === '/' ? 'Root filesystem' : disk.path}</strong><span>{disk.percent}%</span></div><progress value={disk.percent} max="100" aria-label={`${disk.path} storage used`} /><p>{formatBytes(disk.free)} free <span className="muted">/ {formatBytes(disk.total)} total · {disk.path}</span></p></div>) : <p className="empty">Storage information is not available yet.</p>}</Panel>
          </div>
          <Panel title="Network" subtitle="Host interface addresses"><div className="network-grid">{system?.network.length ? system.network.map(iface => <div className="network-item" key={iface.name}><strong>{iface.name} · {iface.is_up == null ? 'Link unknown' : iface.is_up ? 'Link up' : 'Link down'}</strong><p>{iface.addresses.join(' · ') || 'No IP address'}</p><p>↓ {formatBytes(iface.rx_bytes_per_second)}/s · ↑ {formatBytes(iface.tx_bytes_per_second)}/s{iface.speed_mbps ? ` · ${iface.speed_mbps} Mbps link` : ''}</p><p>Errors in/out: {iface.errors_in ?? '—'} / {iface.errors_out ?? '—'} · Drops: {iface.drops_in ?? '—'} / {iface.drops_out ?? '—'} (cumulative since boot; may reset when an interface is recreated)</p></div>) : <p className="empty">Network information is not available yet.</p>}</div></Panel>
        </>}
        {section === 'Overview' && <Services catalog={catalog} health={services} error={servicesError} compact onOpen={() => setSection('Services')} />}
        {section === 'Services' && <Services catalog={catalog} health={services} error={servicesError} />}
        {logSection && <Logs section={section} history={history} historyError={historyError} catalog={catalog} refreshToken={refreshToken} />}
        {section === 'Project' && <Project refreshToken={refreshToken} />}
        {section === 'Overview' && <Backups status={backups} />}
        {section === 'Overview' && <History history={history} error={historyError} />}
        <footer><span>adamserv dashboard <span className="muted">· V1</span></span><span>{system ? `Sampled ${new Date(system.sampled_at).toLocaleString()} · ${system.source === 'collector' ? 'Host collector' : 'Direct host'}${healthy ? ' · Refreshes every 10s' : ' · STALE'}` : 'Waiting for first sample · Refreshes every 10s'}</span></footer>
      </main>
    </div>
  </div>
}
