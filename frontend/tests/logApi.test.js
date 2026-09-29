import assert from 'node:assert/strict'
import test from 'node:test'
import { buildLogUrl } from '../src/logApi.js'

test('log URL includes only supported viewer parameters', () => {
  assert.equal(
    buildLogUrl('server', 'kernel', 'warning', 'disk full', 100),
    '/api/logs/server?severity=warning&limit=100&category=kernel&search=disk+full',
  )
  assert.equal(
    buildLogUrl('samba', '', 'all', '   ', 25),
    '/api/logs/samba?severity=all&limit=25',
  )
})
