import { useEffect, useState } from 'react'

const samplePrompt = 'Explain how photosynthesis turns sunlight into stored chemical energy for a high-school student.'

export default function App() {
  const [prompt, setPrompt] = useState('')
  const [job, setJob] = useState(null)
  const [recent, setRecent] = useState([])
  const [error, setError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [apiKeyConfigured, setApiKeyConfigured] = useState(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [settingsMessage, setSettingsMessage] = useState('')
  const [savingKey, setSavingKey] = useState(false)
  const busy = job && ['queued', 'running'].includes(job.state)

  useEffect(() => {
    loadRecent()
    loadSettings()
  }, [])

  useEffect(() => {
    if (!busy) return
    const timer = setInterval(() => refreshJob(job.id), 1800)
    return () => clearInterval(timer)
  }, [job?.id, job?.state])

  useEffect(() => {
    if (!settingsOpen) return
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setSettingsOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [settingsOpen])

  async function loadRecent() {
    try {
      const response = await fetch('/api/videos')
      if (response.ok) setRecent(await response.json())
    } catch {
      // The main action will show a useful server error if the backend is offline.
    }
  }

  async function loadSettings() {
    try {
      const response = await fetch('/api/settings')
      if (response.ok) {
        const settings = await response.json()
        setApiKeyConfigured(settings.api_key_configured)
      }
    } catch {
      setApiKeyConfigured(null)
    }
  }

  async function refreshJob(id) {
    try {
      const response = await fetch(`/api/videos/${id}`)
      if (!response.ok) throw new Error(await readError(response))
      const next = await response.json()
      setJob(next)
      if (['ready', 'failed'].includes(next.state)) loadRecent()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function createVideo(event) {
    event.preventDefault()
    setError('')
    try {
      const response = await fetch('/api/videos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      if (!response.ok) throw new Error(await readError(response))
      const created = await response.json()
      setJob({ ...created, stage: 'Waiting to start', current: 0, total: 3 })
    } catch (requestError) {
      setError(requestError.message || 'Could not reach the server.')
    }
  }

  async function retry() {
    setError('')
    try {
      const response = await fetch(`/api/videos/${job.id}/retry`, { method: 'POST' })
      if (!response.ok) throw new Error(await readError(response))
      setJob({ ...job, state: 'queued', stage: 'Waiting to retry', error: null })
    } catch (requestError) {
      setError(requestError.message || 'Could not reach the server.')
    }
  }

  async function saveApiKey(event) {
    event.preventDefault()
    setSavingKey(true)
    setSettingsMessage('')
    try {
      const response = await fetch('/api/settings/api-key', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      })
      if (!response.ok) throw new Error(await readError(response))
      setApiKeyConfigured(true)
      setApiKey('')
      setShowApiKey(false)
      setSettingsMessage('Saved. New videos will use this key.')
      setError('')
    } catch (requestError) {
      setSettingsMessage(requestError.message || 'Could not save the key.')
    } finally {
      setSavingKey(false)
    }
  }

  function openSettings() {
    setSettingsMessage('')
    setSettingsOpen(true)
  }

  return (
    <main>
      <header className="topbar">
        <button className="settingsButton" type="button" onClick={openSettings}>
          <span className={`keyDot ${apiKeyConfigured ? 'configured' : ''}`} aria-hidden="true" />
          Settings
        </button>
      </header>

      <section className="hero">
        <div>
          <p className="sectionNote">Animated diagrams, narration, one video</p>
          <h1>What do you want<br />to explain?</h1>
        </div>
        <p className="intro">Write a topic or question. Watch it explained with moving diagrams, illustrations and narration, then download the video.</p>
      </section>

      <section className="workspace">
        <form className="promptForm" onSubmit={createVideo}>
          <div className="fieldHead">
            <label htmlFor="prompt">Lesson prompt</label>
            <span>{prompt.length} / 2000</span>
          </div>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            maxLength="2000"
            placeholder="For example: Explain gradient descent with a simple hill analogy."
            disabled={busy}
          />
          <div className="formFooter">
            <button className="textButton" type="button" onClick={() => setPrompt(samplePrompt)} disabled={busy}>
              Fill in an example
            </button>
            <button className="primary" type="submit" disabled={busy || prompt.trim().length < 3}>
              {busy ? 'Making video...' : 'Make video'}
            </button>
          </div>
        </form>

        {error && (
          <div className="notice error" role="alert">
            <span>{error}</span>
            {!apiKeyConfigured && <button type="button" onClick={openSettings}>Open settings</button>}
          </div>
        )}

        {job && (
          <article className="result">
            {busy && (
              <div className="status">
                <div className="spinner" aria-hidden="true" />
                <div>
                  <p className="statusTitle">{job.stage}</p>
                  <p>Writing, narration and animation can take a few minutes. You can leave this tab open.</p>
                </div>
                <strong>{Math.round(((job.current || 0) / (job.total || 3)) * 100)}%</strong>
              </div>
            )}

            {job.state === 'failed' && (
              <div className="failed">
                <p className="statusTitle">Generation stopped</p>
                <p>{job.error}</p>
                <button className="secondary" onClick={retry}>Try again</button>
              </div>
            )}

            {job.state === 'ready' && (
              <div className="ready">
                <div className="readyHead">
                  <div>
                    <p className="sectionNote">Ready to watch</p>
                    <h2>{job.title || 'Generated lesson'}</h2>
                  </div>
                  <a className="download" href={`/api/videos/${job.id}/download`}>Download MP4</a>
                </div>
                <video
                  key={job.id}
                  controls
                  preload="metadata"
                  src={`/api/videos/${job.id}/file`}
                  onLoadedMetadata={enableAudio}
                  onPlay={enableAudio}
                />
                <p className="audioNote">Narration is included. If it is silent, check whether this browser tab is muted.</p>
              </div>
            )}
          </article>
        )}
      </section>

      {recent.length > 0 && !busy && (
        <section className="recent">
          <div className="recentHead">
            <h2>Recent videos</h2>
            <span>{recent.length}</span>
          </div>
          <div className="recentList">
            {recent.map((item) => (
              <button type="button" key={item.id} onClick={() => setJob(item)}>
                <span>{item.title || 'Untitled lesson'}</span>
                <small>{item.state}</small>
              </button>
            ))}
          </div>
        </section>
      )}

      <footer>Runs locally. Saved API keys stay on the server.</footer>

      {settingsOpen && (
        <div className="modalBackdrop" onMouseDown={() => setSettingsOpen(false)}>
          <section
            className="settingsPanel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="settingsHead">
              <div>
                <p className="sectionNote">Server settings</p>
                <h2 id="settings-title">Gemini API key</h2>
              </div>
              <button className="closeButton" type="button" onClick={() => setSettingsOpen(false)} aria-label="Close settings">Close</button>
            </div>

            <p className="settingsCopy">The saved key is used for script writing and narration. It is stored in the server's local environment file and is never returned to the browser.</p>

            <div className="settingStatus">
              <span className={`keyDot ${apiKeyConfigured ? 'configured' : ''}`} aria-hidden="true" />
              {apiKeyConfigured === null && 'Could not check the server'}
              {apiKeyConfigured === true && 'An API key is saved'}
              {apiKeyConfigured === false && 'No API key is saved'}
            </div>

            <form className="settingsForm" onSubmit={saveApiKey}>
              <label htmlFor="api-key">{apiKeyConfigured ? 'Replace API key' : 'API key'}</label>
              <div className="keyField">
                <input
                  id="api-key"
                  type={showApiKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  minLength="10"
                  maxLength="512"
                  autoComplete="off"
                  spellCheck="false"
                  placeholder="Paste a Gemini API key"
                  autoFocus
                />
                <button type="button" onClick={() => setShowApiKey((visible) => !visible)}>
                  {showApiKey ? 'Hide' : 'Show'}
                </button>
              </div>
              {settingsMessage && <p className="settingsMessage" role="status">{settingsMessage}</p>}
              <div className="settingsActions">
                <button className="secondary" type="button" onClick={() => setSettingsOpen(false)}>Cancel</button>
                <button className="primary" type="submit" disabled={savingKey || apiKey.trim().length < 10}>
                  {savingKey ? 'Saving...' : 'Save key'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>
  )
}

async function readError(response) {
  try {
    const body = await response.json()
    if (Array.isArray(body.detail)) return body.detail[0]?.msg || 'Invalid request.'
    return body.detail || 'Something went wrong.'
  } catch {
    return 'Something went wrong.'
  }
}

function enableAudio(event) {
  event.currentTarget.muted = false
  event.currentTarget.volume = 1
}
