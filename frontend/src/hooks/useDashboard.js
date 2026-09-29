import { useCallback, useEffect, useState } from 'react'

async function getJson(path, signal) {
  const response = await fetch(path, { signal, cache: 'no-store' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `API request failed (${response.status})`)
  }
  return response.json()
}

async function getReadiness(signal) {
  const response = await fetch('/api/ready', { signal, cache: 'no-store' })
  if (response.status !== 200 && response.status !== 503) throw new Error('Readiness unavailable')
  return response.json()
}

export function useDashboard() {
  const [state, setState] = useState({ system: null, catalog: null, services: null, servicesError: null, error: null, catalogError: null, apiOnline: false, loading: true })
  const [generation, setGeneration] = useState(0)
  const refresh = useCallback(() => setGeneration(n => n + 1), [])
  useEffect(() => {
    let disposed = false
    let timer
    let controller
    async function poll() {
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 5000)
      setState(previous => ({ ...previous, loading: true }))
      const [health, system, catalog, services, readiness, history, backups] = await Promise.allSettled([
        getJson('/api/health', controller.signal),
        getJson('/api/system', controller.signal),
        getJson('/api/catalog', controller.signal),
        getJson('/api/services', controller.signal),
        getReadiness(controller.signal),
        getJson('/api/history', controller.signal),
        getJson('/api/backups', controller.signal),
      ])
      clearTimeout(timeout)
      if (disposed) return
      setState(previous => ({
        system: system.status === 'fulfilled' ? system.value : previous.system,
        catalog: catalog.status === 'fulfilled' ? catalog.value : previous.catalog,
        services: services.status === 'fulfilled' ? services.value : previous.services,
        servicesError: services.status === 'fulfilled' ? null : 'Service checks unavailable. Previous results are stale.',
        apiOnline: health.status === 'fulfilled',
        error: system.status === 'fulfilled' ? null : (system.reason.name === 'AbortError' ? 'The API request timed out.' : system.reason.message),
        catalogError: catalog.status === 'fulfilled' ? null : 'Service catalog unavailable. Check the backend configuration.',
        loading: false,
        readiness: readiness.status === 'fulfilled' ? readiness.value : null,
        history: history.status === 'fulfilled' ? history.value : previous.history,
        historyError: history.status === 'fulfilled' ? null : 'Monitoring history unavailable. Retained observations may be stale.',
        backups: backups.status === 'fulfilled' ? backups.value : null,
      }))
      timer = setTimeout(poll, 10000)
    }
    poll()
    return () => { disposed = true; clearTimeout(timer); controller?.abort() }
  }, [generation])
  return { ...state, refresh, refreshToken: generation }
}
