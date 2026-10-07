let sessionPromise

async function controlToken() {
  sessionPromise ||= fetch('/api/session').then(async (response) => {
    if (!response.ok) throw new Error('Could not establish an app session. Refresh the page.')
    return (await response.json()).control_token
  }).catch((error) => {
    sessionPromise = null
    throw error
  })
  return sessionPromise
}

export async function request(path, options = {}) {
  const headers = { ...options.headers }
  if (options.body) headers['Content-Type'] = 'application/json'
  if (options.method && options.method !== 'GET') headers['X-App-Token'] = await controlToken()
  const response = await fetch(path, { ...options, headers })
  if (!response.ok) {
    let message = 'Could not complete the request.'
    try {
      const body = await response.json()
      message = Array.isArray(body.detail) ? body.detail[0]?.msg
        : (body.detail?.message || body.detail || message)
      if (body.detail?.action) message += ` ${body.detail.action}`
    } catch { /* Keep the useful fallback for an unavailable server. */ }
    throw new Error(message)
  }
  return response.json()
}
