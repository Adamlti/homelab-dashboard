import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatBytes } from '../src/format.js'

test('small backups retain meaningful byte units', () => {
  assert.equal(formatBytes(28672), '28.0 KiB')
  assert.equal(formatBytes(0), '0 B')
  assert.equal(formatBytes(500), '500 B')
  assert.equal(formatBytes(1024 ** 3), '1.0 GiB')
  assert.equal(formatBytes(null), '—')
  assert.equal(formatBytes(-1), '—')
})
