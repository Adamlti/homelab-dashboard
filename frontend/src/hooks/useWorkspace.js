import { useEffect, useState } from 'react'

export const logWorkspaces = [
  { name: 'LogsGeneral', label: 'General', hash: '#/logs/general' },
  { name: 'LogsServer', label: 'Server', hash: '#/logs/server' },
  { name: 'LogsSamba', label: 'Samba', hash: '#/logs/samba' },
]

export const workspaces = ['Overview', 'Services', ...logWorkspaces.map(item => item.name), 'Project']
const routes = {
  Overview: '#/overview',
  Services: '#/services',
  Project: '#/project',
  ...Object.fromEntries(logWorkspaces.map(item => [item.name, item.hash])),
}

export const workspaceUrl = name => routes[name] || routes.Overview
export const isLogWorkspace = name => logWorkspaces.some(item => item.name === name)
export const workspaceLabel = name => logWorkspaces.find(item => item.name === name)?.label || name

export function workspaceFromHash(hash) {
  const normalized = (hash || '').toLowerCase().replace(/\/$/, '')
  if (normalized === '#/logs') return 'LogsGeneral'
  return workspaces.find(name => workspaceUrl(name).toLowerCase() === normalized) || 'Overview'
}
export function useWorkspace() {
  const [section, setSection] = useState(() => workspaceFromHash(window.location.hash))
  useEffect(() => {
    const changed = () => setSection(workspaceFromHash(window.location.hash))
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  return [section, name => { window.location.hash = workspaceUrl(name) }]
}
