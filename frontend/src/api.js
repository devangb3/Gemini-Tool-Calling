const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (res.ok) {
    if (res.status === 204) return null
    return res.json()
  }
  const text = await res.text().catch(() => '')
  throw new Error(text || `Request failed: ${res.status}`)
}

