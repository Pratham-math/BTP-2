import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const mocks = vi.hoisted(() => ({ createClient: vi.fn(), api: vi.fn(), setTokenProvider: vi.fn() }))
vi.mock('@supabase/supabase-js', () => ({ createClient: mocks.createClient }))
vi.mock('./api', () => ({ api: mocks.api, setTokenProvider: mocks.setTokenProvider }))
vi.mock('../pages/Independent', () => ({
  Library: () => <h1>Study workspace</h1>, LessonDetail: () => null,
  NewLesson: () => null, ProgressPage: () => null, SourcesPage: () => null, SourceDetail: () => null,
}))
vi.mock('../pages/Classroom', () => ({ Classroom: () => null, CoursePage: () => null, ReviewPage: () => null }))

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const sessionA = { access_token: 'fixture-token-a', user: { id: 'learner-a' } }
const profileA = { id: 'learner-a', display_name: 'Learner A', privilege: 'learner' }
const sessionB = { access_token: 'fixture-token-b', user: { id: 'learner-b' } }
const profileB = { id: 'learner-b', display_name: 'Learner B', privilege: 'learner' }
let initial, requests, onAuthChange, auth

beforeEach(() => {
  vi.clearAllMocks()
  initial = deferred()
  requests = []
  onAuthChange = undefined
  auth = {
    getSession: vi.fn(() => initial.promise),
    onAuthStateChange: vi.fn(callback => {
      onAuthChange = callback
      return { data: { subscription: { unsubscribe: vi.fn() } } }
    }),
    stopAutoRefresh: vi.fn(), signOut: vi.fn(async () => ({ error: null })),
    signInWithOAuth: vi.fn(async () => ({ error: null })),
  }
  mocks.createClient.mockReturnValue({ auth })
  mocks.api.mockImplementation((path, options) => {
    if (path === '/api/config') return Promise.resolve({
      auth_configured: true, google_oauth_verified: true,
      supabase_url: 'https://fixture.supabase.co', supabase_publishable_key: 'fixture-public-key',
    })
    if (path === '/api/me') {
      const request = deferred()
      requests.push({ ...request, options })
      return request.promise
    }
    throw new Error(`Unexpected request: ${path}`)
  })
})
afterEach(() => { cleanup(); vi.useRealTimers() })

async function restore(session = sessionA) {
  await waitFor(() => expect(auth.getSession).toHaveBeenCalled())
  await act(async () => initial.resolve({ data: { session }, error: null }))
}
async function signedIn() {
  render(<App />)
  await restore()
  await waitFor(() => expect(requests).toHaveLength(1))
  await act(async () => requests[0].resolve(profileA))
  await screen.findByRole('heading', { name: 'Study workspace' })
}
function expectNoLogin() {
  expect(screen.queryByRole('button', { name: /Continue with Google/ })).toBeNull()
}

describe('authentication screen transitions', () => {
  it('never shows login while restoring a session or waiting for its profile', async () => {
    render(<App />)
    expect(screen.getByText('Opening your workspace…')).toBeTruthy()
    expectNoLogin()
    await restore()
    await waitFor(() => expect(requests).toHaveLength(1))
    expect(screen.getByText('Opening your workspace…')).toBeTruthy()
    expectNoLogin()
    expect(screen.queryByRole('heading', { name: 'Study workspace' })).toBeNull()
    await act(async () => requests[0].resolve(profileA))
    expect(await screen.findByRole('heading', { name: 'Study workspace' })).toBeTruthy()
    expectNoLogin()
  })

  it('shows login once a genuinely signed-out session is known', async () => {
    render(<App />)
    await restore(null)
    expect(await screen.findByRole('button', { name: /Continue with Google/ })).toBeTruthy()
    expect(requests).toHaveLength(0)
  })

  it('offers retry instead of login when an authenticated profile request fails', async () => {
    render(<App />)
    await restore()
    await waitFor(() => expect(requests).toHaveLength(1))
    await act(async () => requests[0].reject(new Error('Teaching API unavailable')))
    expect(await screen.findByRole('heading', { name: 'Your workspace could not load' })).toBeTruthy()
    expect(screen.getByText('Teaching API unavailable')).toBeTruthy()
    expectNoLogin()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('Opening your workspace…')).toBeTruthy()
    await waitFor(() => expect(requests).toHaveLength(2))
    await act(async () => requests[1].resolve(profileA))
    expect(await screen.findByRole('heading', { name: 'Study workspace' })).toBeTruthy()
  })

  it('offers retry when the profile request times out instead of loading forever', async () => {
    render(<App />)
    await restore()
    await waitFor(() => expect(requests).toHaveLength(1))
    // Start a retry with fake timers so the timeout does not delay the suite.
    await act(async () => requests[0].reject(new Error('Temporary failure')))
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(requests).toHaveLength(2)
    requests[1].options.signal.addEventListener('abort', () => requests[1].reject(new DOMException('Aborted', 'AbortError')))
    await act(async () => vi.advanceTimersByTimeAsync(15000))
    expect(screen.getByText('Loading your account took too long. Please try again.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
    expectNoLogin()
    expect(requests[1].options.signal.aborted).toBe(true)
  })

  it('ignores a late profile response after signing out', async () => {
    render(<App />)
    await restore()
    await waitFor(() => expect(requests).toHaveLength(1))
    act(() => onAuthChange('SIGNED_OUT', null))
    await act(async () => requests[0].resolve(profileA))
    expect(await screen.findByRole('button', { name: /Continue with Google/ })).toBeTruthy()
    expect(screen.queryByText('Learner A')).toBeNull()
  })

  it('hides the old profile during an account switch and ignores its pending refresh', async () => {
    await signedIn()
    act(() => onAuthChange('TOKEN_REFRESHED', { ...sessionA, access_token: 'fixture-refreshed-a' }))
    await waitFor(() => expect(requests).toHaveLength(2))
    act(() => onAuthChange('SIGNED_IN', sessionB))
    await waitFor(() => expect(requests).toHaveLength(3))
    expect(screen.getByText('Opening your workspace…')).toBeTruthy()
    expect(screen.queryByText('Learner A')).toBeNull()
    expectNoLogin()
    await act(async () => requests[1].resolve(profileA))
    expect(screen.getByText('Opening your workspace…')).toBeTruthy()
    await act(async () => requests[2].resolve(profileB))
    expect(await screen.findByText('Learner B')).toBeTruthy()
    expect(screen.queryByText('Learner A')).toBeNull()
  })

  it('keeps the workspace mounted during a same-user token refresh', async () => {
    await signedIn()
    const workspace = screen.getByRole('heading', { name: 'Study workspace' })
    act(() => onAuthChange('TOKEN_REFRESHED', { ...sessionA, access_token: 'fixture-refreshed-a' }))
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(screen.getByRole('heading', { name: 'Study workspace' })).toBe(workspace)
    expect(screen.queryByText('Opening your workspace…')).toBeNull()
    expectNoLogin()
    await act(async () => requests[1].resolve(profileA))
    expect(screen.getByRole('heading', { name: 'Study workspace' })).toBe(workspace)
  })

  it('does not let a late initial session overwrite a newer sign-out event', async () => {
    render(<App />)
    await waitFor(() => expect(auth.onAuthStateChange).toHaveBeenCalled())
    act(() => onAuthChange('SIGNED_OUT', null))
    await restore(sessionA)
    expect(await screen.findByRole('button', { name: /Continue with Google/ })).toBeTruthy()
    expect(requests).toHaveLength(0)
  })

  it('rejects a profile that does not belong to the current session', async () => {
    render(<App />)
    await restore()
    await waitFor(() => expect(requests).toHaveLength(1))
    await act(async () => requests[0].resolve(profileB))
    expect(await screen.findByRole('heading', { name: 'Your workspace could not load' })).toBeTruthy()
    expect(screen.queryByText('Learner B')).toBeNull()
    expectNoLogin()
  })

  it('leaves the loader when initialization fails', async () => {
    render(<App />)
    await waitFor(() => expect(auth.getSession).toHaveBeenCalled())
    await act(async () => initial.resolve({ data: { session: null }, error: new Error('Session unavailable') }))
    expect(await screen.findByText('Session unavailable')).toBeTruthy()
    expect(screen.queryByText('Opening your workspace…')).toBeNull()
  })

  it('restores the session under React StrictMode', async () => {
    render(<StrictMode><App /></StrictMode>)
    await restore()
    await waitFor(() => expect(requests).toHaveLength(1))
    expect(screen.getByText('Opening your workspace…')).toBeTruthy()
    expectNoLogin()
    await act(async () => requests[0].resolve(profileA))
    expect(await screen.findByRole('heading', { name: 'Study workspace' })).toBeTruthy()
  })
})
