function cell(value) {
  let text = String(value ?? '')
  // Keep names/details literal when opened in a spreadsheet.
  const first = [...text].find(character => character.codePointAt(0) > 32 && character.trim())
  if ((first && "=+@-".includes(first)) || /^[\t\r\n]/.test(text)) text = "'" + text
  return '"' + text.replaceAll('"', '""') + '"'
}

export function logsCsv(rows) {
  return '\uFEFF' + ['Date,Name,Details', ...rows.map(row => [row.at, row.name, row.detail].map(cell).join(','))].join('\r\n') + '\r\n'
}

export function downloadLogs(rows, kind) {
  const url = URL.createObjectURL(new Blob([logsCsv(rows)], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `adamserv-${kind}-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
