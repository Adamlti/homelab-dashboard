import { useState } from 'react'
import { isLogWorkspace, logWorkspaces, workspaceUrl } from '../hooks/useWorkspace'

const primary = [
  { name: 'Overview', icon: '◫' },
  { name: 'Services', icon: '▤' },
]

function NavigationLink({ item, section }) {
  const active = section === item.name
  return <a href={workspaceUrl(item.name)} className={active ? 'nav-item active' : 'nav-item'} aria-current={active ? 'page' : undefined}>
    <span aria-hidden="true">{item.icon}</span>{item.label || item.name}
  </a>
}

export function SidebarNavigation({ section }) {
  const logsActive = isLogWorkspace(section)
  const [expansion, setExpansion] = useState({ section, open: logsActive })
  // A newly navigated log route reveals its active child, including Back/Forward.
  const logsOpen = expansion.section === section ? expansion.open : logsActive || expansion.open

  return <nav className="sidebar-nav" aria-label="Main navigation">
    {primary.map(item => <NavigationLink item={item} section={section} key={item.name} />)}
    <div className={logsActive ? 'nav-log-group active' : 'nav-log-group'}>
      <button className="nav-item nav-parent" type="button" aria-expanded={logsOpen} aria-controls="logs-alerts-menu" onClick={() => setExpansion({ section, open: !logsOpen })}>
        <span aria-hidden="true">≡</span><span className="nav-parent-label">Logs / Alerts</span><span className={logsOpen ? 'nav-chevron open' : 'nav-chevron'} aria-hidden="true">›</span>
      </button>
      {logsOpen && <div className="nav-submenu" id="logs-alerts-menu">
        {logWorkspaces.map(item => <a href={item.hash} key={item.name} className={section === item.name ? 'nav-subitem active' : 'nav-subitem'} aria-current={section === item.name ? 'page' : undefined}>{item.label}</a>)}
      </div>}
    </div>
    <NavigationLink item={{ name: 'Project', icon: '☷' }} section={section} />
  </nav>
}
