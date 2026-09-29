import assert from 'node:assert/strict'
import { test } from 'node:test'
import { chartSegments } from '../src/historyChart.js'

const point = (minute, value) => ({ at: new Date(Date.UTC(2026, 0, 1, 0, minute)).toISOString(), cpu: value })
test('history breaks at missing samples and sampling outages', () => {
  const segments = chartSegments([point(0, 20), point(1, 30), point(5, 50), point(6, null), point(7, 60)], 'cpu')
  assert.deepEqual(segments.map(segment => segment.length), [2, 1, 1])
  assert.equal(segments[0][0][1], 80)
  assert.equal(segments.at(-1)[0][0], 300)
})
test('empty and single-sample charts have finite coordinates', () => {
  assert.deepEqual(chartSegments([], 'cpu'), [])
  assert.deepEqual(chartSegments([point(0, 15)], 'cpu'), [[[0, 85]]])
})
