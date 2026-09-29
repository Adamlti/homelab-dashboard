// Break lines at missing samples; never draw a continuous line across an outage.
export function chartSegments(points, metric) {
  const times = points.map(point => Date.parse(point.at))
  const start = times[0]
  const span = Math.max(60000, times.at(-1) - start)
  const segments = []
  let current = []
  let previous = null
  for (const point of points) {
    const time = Date.parse(point.at)
    const value = point[metric]
    if (value == null || !Number.isFinite(value) || !Number.isFinite(time) || (previous != null && (time - previous > 120000 || time < previous))) {
      if (current.length) segments.push(current)
      current = []
    }
    if (value != null && Number.isFinite(value) && Number.isFinite(time)) {
      current.push([((time - start) / span) * 300, 100 - Math.min(100, Math.max(0, value))])
    }
    previous = time
  }
  if (current.length) segments.push(current)
  return segments
}
