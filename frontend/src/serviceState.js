export function serviceState(result, configured, unavailable, now, staleAfter = 30) {
  if (!configured) return { status: 'not_configured', label: 'Not configured' }
  if (!result || !result.checked_at || result.status === 'not_configured') return { status: 'unknown', label: 'Awaiting check' }
  const age = (now - Date.parse(result.checked_at)) / 1000
  const stale = result.stale || unavailable || (result.checked_at && (!Number.isFinite(age) || age > staleAfter || age < -5))
  if (stale) return { status: 'stale', label: `Stale · last ${result.last_status || result.status}` }
  const labels = { online: 'Online', offline: 'Offline', timeout: 'Timed out', error: 'Check error', unknown: 'Awaiting check' }
  return { status: result.status, label: labels[result.status] || 'Awaiting check' }
}
