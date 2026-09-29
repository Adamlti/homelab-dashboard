import { test } from 'node:test'
import assert from 'node:assert/strict'
import { logsCsv } from '../src/logsCsv.js'

test('CSV includes date, name, details and preserves quotes, newlines and Unicode', () => {
  const csv = logsCsv([{at:'2026-09-13T12:00:00Z', name:'Pi-hole', detail:'Said "hello", then\nrecovered → online'}])
  assert.equal(csv, '\uFEFFDate,Name,Details\r\n"2026-09-13T12:00:00Z","Pi-hole","Said ""hello"", then\nrecovered → online"\r\n')
})
test('spreadsheet formulas are exported as literal text', () => {
  const csv = logsCsv([{at:'2026-09-13',name:'=HYPERLINK("bad")',detail:'  +SUM(1,2)'}])
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'))
  assert.ok(csv.includes('"\'  +SUM(1,2)"'))
})
test('empty export still has the requested headers', () => {
  assert.equal(logsCsv([]), '\uFEFFDate,Name,Details\r\n')
})
