export function buildLogUrl(provider, category, severity, search, limit) {
  const query = new URLSearchParams({ severity, limit: String(limit) })
  if (category) query.set('category', category)
  if (search.trim()) query.set('search', search.trim())
  return `/api/logs/${provider}?${query}`
}
