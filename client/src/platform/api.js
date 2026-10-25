let tokenProvider = async () => null
export function setTokenProvider(provider) { tokenProvider = provider }
export async function api(path, options = {}) {
  const token = await tokenProvider(), headers = { ...options.headers }
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch((import.meta.env.VITE_API_BASE_URL || '') + path, { ...options, headers })
  if (!response.ok) {
    let message = 'The service could not complete this request. Please try again.'
    try { const body = await response.json(); message = Array.isArray(body.detail) ? body.detail.map(x => x.msg).join(' ') : body.detail?.message || body.detail || message } catch {}
    const error = new Error(message); error.status = response.status; throw error
  }
  return response.json()
}
export const post = (path, body) => api(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
