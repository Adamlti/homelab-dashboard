export async function projectRequest(path, options = {}) {
  const response = await fetch(`/api/${path}`, {
    ...options, cache: 'no-store', signal: AbortSignal.timeout(7000),
    headers: { 'Content-Type': 'application/json', 'X-Dashboard-Request': 'tasks' },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    if (response.status === 403) {
      throw new Error(`Save blocked by the dashboard's same-origin protection. Open the dashboard directly at its configured address and retry; the proxy must preserve Host. ${typeof body.detail === 'string' ? body.detail : ''}`)
    }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save changes. Please retry.')
  }
  return response.json()
}
