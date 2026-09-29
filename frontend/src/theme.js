export function storedTheme() {
  try {
    const value = localStorage.getItem('adamserv-theme')
    if (value === 'light' || value === 'dark') return value
  } catch { /* A private browser may disable local storage. */ }
  return 'dark'
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme
  try { localStorage.setItem('adamserv-theme', theme) } catch { /* Still apply for this visit. */ }
}
