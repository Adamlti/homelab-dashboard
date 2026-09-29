import test from 'node:test'
import assert from 'node:assert/strict'
import { serviceState } from '../src/serviceState.js'

const now = Date.parse('2026-09-12T20:00:00Z')
const result = { status: 'online', checked_at: new Date(now - 1000).toISOString() }

test('fresh observations retain online/offline/timeout status', () => {
  for (const status of ['online', 'offline', 'timeout']) {
    assert.equal(serviceState({ ...result, status }, true, false, now).status, status)
  }
})
test('results expire without another successful API request', () => {
  assert.equal(serviceState(result, true, false, now + 31000).status, 'stale')
})
test('API failure immediately marks retained observations stale', () => {
  assert.equal(serviceState(result, true, true, now).label, 'Stale · last online')
})
test('server stale result preserves last status', () => {
  assert.equal(serviceState({ ...result, status: 'stale', stale: true, last_status: 'timeout' }, true, false, now).label, 'Stale · last timeout')
})
test('unconfigured and never-observed services are distinct', () => {
  assert.equal(serviceState(null, false, true, now).status, 'not_configured')
  assert.equal(serviceState(null, true, true, now).status, 'unknown')
})

test('an unobserved pending check remains unknown on API failure', () => {
  assert.equal(serviceState({ status: 'unknown', checked_at: null }, true, true, now).status, 'unknown')
})
