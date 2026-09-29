import assert from 'node:assert/strict'
import test from 'node:test'
import { isLogWorkspace, workspaceFromHash, workspaceUrl } from '../src/hooks/useWorkspace.js'

test('log workspaces support deep links and the legacy log link', () => {
  assert.equal(workspaceFromHash('#/logs/general'), 'LogsGeneral')
  assert.equal(workspaceFromHash('#/logs/server/'), 'LogsServer')
  assert.equal(workspaceFromHash('#/logs/samba'), 'LogsSamba')
  assert.equal(workspaceFromHash('#/logs'), 'LogsGeneral')
  assert.equal(workspaceUrl('LogsServer'), '#/logs/server')
  assert.equal(isLogWorkspace('LogsSamba'), true)
})

test('unknown hashes return to Overview', () => {
  assert.equal(workspaceFromHash('#/not-a-route'), 'Overview')
})
