let tokenProvider = async () => null
// Set when the UI is hosted apart from the API (e.g. static site + ngrok tunnel).
const BASE = import.meta.env.VITE_API_BASE_URL || ''
// ngrok's free tunnel shows a warning page to browsers unless this header is sent.
const TUNNEL = BASE ? { 'ngrok-skip-browser-warning': '1' } : {}
export function setTokenProvider(provider) { tokenProvider = provider }
export async function api(path, options = {}) {
  const token = await tokenProvider(), headers = { ...TUNNEL, ...options.headers }
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch(BASE + path, { ...options, headers })
  if (!response.ok) {
    let message = 'The service could not complete this request. Please try again.'
    try { const body = await response.json(); message = Array.isArray(body.detail) ? body.detail.map(x => x.msg).join(' ') : body.detail?.message || body.detail || message } catch {}
    const error = new Error(message); error.status = response.status; throw error
  }
  return response.json()
}
export const post = (path, body) => api(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
// Signed media paths are relative to the API. Through a tunnel, <audio>/<video>/<img>
// cannot send the header above, so fetch the file and play it from a blob URL.
// ponytail: blob URLs are never revoked; a session holds a handful of short clips.
export async function media(url) {
  if (!BASE || !url || !url.startsWith('/')) return url
  const response = await fetch(BASE + url, { headers: TUNNEL })
  if (!response.ok) throw new Error('Could not load this media file. Please try again.')
  return URL.createObjectURL(await response.blob())
}
