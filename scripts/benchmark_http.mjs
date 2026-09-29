// Fixed-worker HTTP load avoids client-side pool scheduling in the Python burst.
import http from 'node:http'
import { performance } from 'node:perf_hooks'
const origin = process.argv[2] || 'http://127.0.0.1:8008'
const agent = new http.Agent({ keepAlive: true, maxSockets: 100 })
const paths = ['/api/health', '/api/system', '/api/services', '/api/catalog']
const times = [], errors = []
let next = 0
const start = performance.now()
await Promise.all(Array.from({ length: 100 }, async () => {
  while (next < 400) {
    const i = next++, before = performance.now()
    await new Promise(resolve => {
      const req = http.get(new URL(paths[i % paths.length], origin), { agent, timeout: 15000 }, res => {
        if (res.statusCode !== 200) errors.push(res.statusCode)
        res.resume()
        res.on('end', resolve)
      })
      req.on('error', err => { errors.push(err.code); resolve() })
      req.on('timeout', () => req.destroy(new Error('timeout')))
    })
    times.push(performance.now() - before)
  }
}))
agent.destroy()
times.sort((a, b) => a - b)
console.log(JSON.stringify({ requests: 400, concurrency: 100, p50_ms: times[200], p95_ms: times[379], max_ms: times.at(-1), errors, total_ms: performance.now() - start }))
