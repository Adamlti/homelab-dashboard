import test from 'node:test'
import assert from 'node:assert/strict'
import { projectRequest } from '../src/projectApi.js'

test('origin rejection explains the failed write and proxy Host requirement', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Cross-origin project writes are not allowed' }), { status: 403 })
  try {
    await assert.rejects(projectRequest('tasks', { method: 'POST', body: '{}' }), /same-origin protection.*preserve Host/)
  } finally { globalThis.fetch = original }
})
