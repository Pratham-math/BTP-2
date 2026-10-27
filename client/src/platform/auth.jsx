import { createContext, useContext, useEffect, useState } from 'react'
import { createClient } from '@supabase/supabase-js'
import { api, setTokenProvider } from './api'
const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)
const LOCAL_TOKEN = 'btp2:local-token'
function localSession(token) {
  try {
    const claims = JSON.parse(atob(token.split('.')[1].replaceAll('-', '+').replaceAll('_', '/')))
    return claims.exp * 1000 > Date.now() ? { user: { id: claims.sub }, access_token: token } : null
  } catch { return null }
}
export function AuthProvider({ children }) {
  const [config, setConfig] = useState(null), [client, setClient] = useState(null), [session, setSession] = useState(null)
  const [profileState, setProfileState] = useState(null), [profileAttempt, setProfileAttempt] = useState(0)
  const [error, setError] = useState(''), [initializing, setInitializing] = useState(true)
  const userId = session?.user.id, accessToken = session?.access_token
  // A token refresh may reuse this user's validated profile, but an account switch cannot.
  const profile = profileState?.userId === userId ? profileState?.profile : null
  const profileError = profileState?.userId === userId && profileState?.accessToken === accessToken && profileState?.attempt === profileAttempt ? profileState?.error : ''
  const loading = initializing || Boolean(session && !profile && !profileError)
  useEffect(() => {
    let active = true, subscription, instance, authRevision = 0
    api('/api/config').then(async config => {
      if (!active) return
      setConfig(config)
      if (config.auth_mode === 'local') {
        // Local profile: server-issued token kept in this browser.
        let stored = null
        try { stored = localSession(localStorage.getItem(LOCAL_TOKEN) || '') } catch {}
        setTokenProvider(async () => { try { return localStorage.getItem(LOCAL_TOKEN) } catch { return null } })
        setSession(stored); setInitializing(false); return
      }
      if (!config.auth_configured) { setInitializing(false); return }
      instance = createClient(config.supabase_url, config.supabase_publishable_key, { auth: { flowType: 'pkce', autoRefreshToken: true, persistSession: true, detectSessionInUrl: true } })
      setClient(instance)
      setTokenProvider(async () => (await instance.auth.getSession()).data.session?.access_token)
      // Keep the listener synchronous; profile requests run outside the auth SDK's lock.
      subscription = instance.auth.onAuthStateChange((_event, nextSession) => {
        if (!active) return
        authRevision += 1
        setSession(nextSession)
        setProfileState(previous => nextSession && previous?.userId === nextSession.user.id ? previous : null)
        setError('')
        setInitializing(false)
      }).data.subscription
      const initialRevision = authRevision
      const result = await instance.auth.getSession()
      // A newer event (especially SIGNED_OUT) wins over a late storage read.
      if (!active || authRevision !== initialRevision) return
      if (result.error) throw result.error
      setSession(result.data.session)
      setInitializing(false)
    }).catch(error => { if (active) { setError(error.message); setInitializing(false) } })
    return () => { active = false; subscription?.unsubscribe(); instance?.auth.stopAutoRefresh(); setTokenProvider(async () => null) }
  }, [])
  useEffect(() => {
    if (!userId || !accessToken) return
    let active = true
    const controller = new AbortController()
    let timedOut = false
    const timeout = setTimeout(() => { timedOut = true; controller.abort() }, 15000)
    api('/api/me', { signal: controller.signal }).then(profile => {
      if (!active) return
      if (profile.id !== userId) throw new Error('Your account could not be verified. Please sign out and try again.')
      setProfileState({ userId, accessToken, attempt: profileAttempt, profile, error: '' })
      setError('')
    }).catch(error => {
      if (active) setProfileState({ userId, accessToken, attempt: profileAttempt, profile: null,
        error: timedOut ? 'Loading your account took too long. Please try again.' : error.message })
    }).finally(() => clearTimeout(timeout))
    return () => { active = false; clearTimeout(timeout); controller.abort() }
  }, [userId, accessToken, profileAttempt])
  function retryProfile() { setError(''); setProfileAttempt(attempt => attempt + 1) }
  async function localAuth(kind, body) {
    setError('')
    try {
      const result = await api(`/api/local/${kind}`, { method: 'POST', body: JSON.stringify(body) })
      localStorage.setItem(LOCAL_TOKEN, result.token); setSession(localSession(result.token))
    } catch (e) { setError(e.message) }
  }
  async function signIn() {
    setError('')
    const { error } = await client.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin + '/auth/callback' } })
    if (error) setError(error.message)
  }
  async function signOut() {
    if (config?.auth_mode === 'local') { localStorage.removeItem(LOCAL_TOKEN); setSession(null); setProfileState(null); return }
    const { error } = await client.auth.signOut()
    if (error) setError(error.message); else { setSession(null); setProfileState(null) }
  }
  return <AuthContext.Provider value={{ config, profile, session, loading, error: error || profileError, signIn, signOut, retryProfile, localAuth }}>{children}</AuthContext.Provider>
}
