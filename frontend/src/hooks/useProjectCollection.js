import { useCallback, useEffect, useRef, useState } from 'react'
import { projectRequest } from '../projectApi'

// Refresh waits for in-flight writes, and older reads cannot replace saved data.
export function useProjectCollection(path, refreshToken) {
  const [rows, setRows] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const alive = useRef(false)
  const pending = useRef(false)
  const queued = useRef(false)
  const generation = useRef(0)
  const load = useCallback(async () => {
    if (pending.current) { queued.current = true; return }
    const token = ++generation.current
    try {
      const data = await projectRequest(path)
      if (alive.current && token === generation.current) {
        setRows(data); setLoaded(true); setError(null)
      }
    } catch (err) {
      if (alive.current && token === generation.current) setError(err.message)
    }
  }, [path])
  useEffect(() => {
    alive.current = true
    // Invalidate outstanding reads across StrictMode cleanup/restart too.
    const invalidate = () => { generation.current += 1 }
    const timer = setTimeout(load, 0)
    return () => { alive.current = false; invalidate(); clearTimeout(timer) }
  }, [load, refreshToken])

  async function save(operation) {
    if (pending.current) return
    pending.current = true
    ++generation.current
    setBusy(true); setError(null)
    try { await operation() }
    catch (err) { if (alive.current) setError(err.message) }
    finally {
      pending.current = false
      if (alive.current) {
        setBusy(false)
        if (queued.current) { queued.current = false; void load() }
      }
    }
  }
  return { rows, setRows, loaded, busy, error, alive, load, save }
}
