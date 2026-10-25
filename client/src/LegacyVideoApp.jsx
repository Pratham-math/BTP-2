import { useEffect, useRef, useState } from 'react'
import { request } from './api'
import GenerationOptions from './components/GenerationOptions'
import Readiness from './components/Readiness'

const samplePrompt = 'Explain how photosynthesis turns sunlight into stored chemical energy for a high-school student.'
const stopped = ['ready', 'failed', 'interrupted', 'cancelled']
const defaultSelection = { mode: 'cloud', text_model: '', voice: '', render_profile: '720p24', speech_rate: 1 }

export default function LegacyVideoApp() {
  const [prompt, setPrompt] = useState(() => localStorage.getItem('video-prompt') || '')
  const [job, setJob] = useState(null)
  const [recent, setRecent] = useState([])
  const [error, setError] = useState('')
  const [selection, setSelection] = useState(defaultSelection)
  const [providers, setProviders] = useState(null)
  const [runtime, setRuntime] = useState(null)
  const [readiness, setReadiness] = useState(null)
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [apiKeyConfigured, setApiKeyConfigured] = useState(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [settingsMessage, setSettingsMessage] = useState('')
  const [savingKey, setSavingKey] = useState(false)
  const [, tick] = useState(0)
  const pendingRequest = useRef(null)
  const settingsPanel = useRef(null)
  const busy = job && ['queued', 'running', 'cancelling'].includes(job.state)

  useEffect(() => {
    loadRecent()
    request('/api/settings').then((settings) => {
      setApiKeyConfigured(settings.api_key_configured)
      setSelection(settings.selection)
    }).catch((e) => setError(e.message))
    request('/api/runtime').then(setRuntime).catch(() => {})
    loadProviders()
    const active = localStorage.getItem('video-job')
    if (active) refreshJob(active)
  }, [])

  useEffect(() => { localStorage.setItem('video-prompt', prompt) }, [prompt])
  useEffect(() => {
    if (!busy) return
    const poll = setInterval(() => refreshJob(job.id), 1800)
    const clock = setInterval(() => tick((value) => value + 1), 1000)
    return () => { clearInterval(poll); clearInterval(clock) }
  }, [job?.id, job?.state])

  useEffect(() => {
    if (!settingsOpen) { setApiKey(''); setShowApiKey(false); return }
    const previous = document.activeElement
    settingsPanel.current?.querySelector('button')?.focus()
    const keyboard = (event) => {
      if (event.key === 'Escape') setSettingsOpen(false)
      if (event.key === 'Tab') {
        const controls = [...settingsPanel.current.querySelectorAll('button:not(:disabled), input:not(:disabled)')]
        const first = controls[0], last = controls.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }
    window.addEventListener('keydown', keyboard)
    return () => { window.removeEventListener('keydown', keyboard); previous?.focus() }
  }, [settingsOpen])

  async function loadRecent() { try { setRecent(await request('/api/videos')) } catch {} }
  async function loadProviders() { try { setProviders(await request('/api/providers')) } catch {} }
  async function refreshJob(id) {
    try {
      const next = await request(`/api/videos/${id}`)
      setJob(next)
      localStorage.setItem('video-job', id)
      if (stopped.includes(next.state)) loadRecent()
    } catch (e) { setError(e.message) }
  }

  function chooseSettings(next) {
    setSelection(next)
    setReadiness(null)
    setError('')
  }

  async function checkSetup() {
    setChecking(true); setError(''); setReadiness(null)
    try {
      setReadiness(await request('/api/preflight', { method: 'POST', body: JSON.stringify({ settings: selection, probe: true }) }))
      await loadProviders()
    } catch (e) { setError(e.message) }
    finally { setChecking(false) }
  }

  async function createVideo(event) {
    event.preventDefault()
    if (submitting || busy) return
    setSubmitting(true); setError('')
    const signature = JSON.stringify({ prompt: prompt.trim(), settings: selection })
    if (pendingRequest.current?.signature !== signature) pendingRequest.current = {
      signature, id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (v) => v.toString(16).padStart(2, '0')).join(''),
    }
    try {
      const created = await request('/api/videos', { method: 'POST', body: JSON.stringify({ prompt,
        settings: selection, request_id: pendingRequest.current.id }) })
      localStorage.setItem('video-job', created.id)
      setJob({ ...created, stage: 'Waiting to start', current: 0, total: 3 })
      pendingRequest.current = null
      await refreshJob(created.id)
    } catch (e) { setError(e.message || 'Could not reach the server.') }
    finally { setSubmitting(false) }
  }

  async function retry() {
    setSubmitting(true); setError('')
    try {
      await request(`/api/videos/${job.id}/retry`, { method: 'POST' })
      setJob({ ...job, state: 'queued', stage: 'Waiting to resume', error: null })
    } catch (e) { setError(e.message) }
    finally { setSubmitting(false) }
  }

  async function cancel() {
    setError('')
    try {
      await request(`/api/videos/${job.id}/cancel`, { method: 'POST' })
      setJob({ ...job, state: 'cancelling', stage: 'Cancelling; waiting for owned work to stop' })
    } catch (e) { setError(e.message) }
  }

  async function saveApiKey(event) {
    event.preventDefault(); setSavingKey(true); setSettingsMessage('')
    try {
      await request('/api/settings/api-key', { method: 'PUT', body: JSON.stringify({ api_key: apiKey }) })
      setApiKeyConfigured(true); setApiKey(''); setShowApiKey(false)
      setSettingsMessage('Saved. Cloud videos will use this key.'); setReadiness(null)
    } catch (e) { setSettingsMessage(e.message) }
    finally { setSavingKey(false) }
  }

  async function savePreset() {
    try {
      await request('/api/settings', { method: 'PUT', body: JSON.stringify(selection) })
      setSettingsMessage('Saved the selected mode, model, voice and video quality.')
    } catch (e) { setSettingsMessage(e.message) }
  }

  async function confirmRuntimeRestart() {
    try {
      await request('/api/providers/ollama/confirm-restart', { method: 'POST', body: JSON.stringify({ confirm_restarted: true }) })
      await loadProviders()
      setReadiness(null)
      setSettingsMessage('Restart confirmed. Run Check setup before resuming local generation.')
    } catch (e) { setSettingsMessage(e.message) }
  }

  function openSettings() { setSettingsMessage(''); setSettingsOpen(true) }
  const elapsed = job?.started_at ? Math.max(0, Math.floor(((job.finished_at ? Date.parse(job.finished_at) : Date.now()) - Date.parse(job.started_at)) / 1000)) : 0

  return (
    <main>
      <header className="topbar"><button className="settingsButton" type="button" onClick={openSettings}>
        <span className={`keyDot ${apiKeyConfigured ? 'configured' : ''}`} aria-hidden="true" />Settings
      </button></header>
      <section className="hero">
        <div><p className="sectionNote">Animated diagrams, narration, one video</p><h1>What do you want<br />to explain?</h1></div>
        <p className="intro">Write a topic or question. Watch it explained with moving diagrams and narration, then download the video.</p>
      </section>
      <section className="workspace">
        <GenerationOptions selection={selection} onChange={chooseSettings} providers={providers} runtime={runtime} disabled={busy || submitting || checking} />
        <Readiness result={readiness} checking={checking} onCheck={checkSetup} owner={runtime?.owner_settings} disabled={busy} />
        <form className="promptForm" onSubmit={createVideo}>
          <div className="fieldHead"><label htmlFor="prompt">Lesson prompt</label><span>{prompt.length} / 2000</span></div>
          <textarea id="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength="2000"
            placeholder="For example: Explain gradient descent with a simple hill analogy." disabled={busy || submitting} />
          <div className="formFooter">
            <button className="textButton" type="button" onClick={() => setPrompt(samplePrompt)} disabled={busy || submitting}>Fill in an example</button>
            <button className="primary" type="submit" disabled={busy || submitting || checking || prompt.trim().length < 3}>
              {busy ? 'Making video…' : submitting ? 'Starting…' : 'Make video'}
            </button>
          </div>
        </form>
        {error && <div className="notice error" role="alert"><span>{error}</span><button type="button" onClick={openSettings}>Settings</button></div>}
        {job && <article className="result">
          {busy && <div className="status" role="status">
            <div className="spinner" aria-hidden="true" />
            <div><p className="statusTitle">{job.stage}</p><p>{Math.floor(elapsed / 60)}m {elapsed % 60}s elapsed · {job.mode === 'local' ? 'Local providers' : 'Gemini cloud API'}</p>
              <p>{job.state === 'cancelling' ? 'An in-flight inference call may need to finish before the slot is released.' : 'Progress is saved on the backend. You can close this tab and return.'}</p></div>
            <button className="secondary" onClick={cancel} disabled={job.state === 'cancelling'}>Cancel</button>
          </div>}
          {['failed', 'interrupted', 'cancelled'].includes(job.state) && <div className="failed">
            <p className="statusTitle">{job.state === 'interrupted' ? 'Generation was interrupted' : job.state === 'cancelled' ? 'Generation cancelled' : 'Generation stopped'}</p>
            <p>{job.error}</p>{job.action && <p>{job.action}</p>}
            <button className="secondary" onClick={retry} disabled={submitting}>Resume saved job</button>
          </div>}
          {job.state === 'ready' && <div className="ready">
            <div className="readyHead"><div><p className="sectionNote">Ready to watch · {job.mode === 'local' ? 'Local providers' : 'Gemini'}</p><h2>{job.title || 'Generated lesson'}</h2></div>
              <a className="download" href={`/api/videos/${job.id}/download`}>Download MP4</a></div>
            <video key={job.id} controls preload="metadata" src={`/api/videos/${job.id}/file`}
              onError={() => { setError('Playback failed. Check the job status or try downloading the MP4.'); refreshJob(job.id) }} />
            <p className="audioNote">Narration is included. If it is silent, check whether this browser tab is muted.</p>
          </div>}
        </article>}
      </section>
      {recent.length > 0 && !busy && <section className="recent">
        <div className="recentHead"><h2>Recent videos</h2><span>{recent.length}</span></div>
        <div className="recentList">{recent.map((item) => <button type="button" key={item.id} onClick={() => refreshJob(item.id)}>
          <span>{item.title || 'Untitled lesson'}</span><small>{item.mode} · {item.state}</small>
        </button>)}</div>
      </section>}
      <footer>Generation runs on {runtime?.host || 'the backend computer'}. Local mode uses Ollama and Piper.</footer>
      {settingsOpen && <div className="modalBackdrop" onMouseDown={() => setSettingsOpen(false)}>
        <section ref={settingsPanel} className="settingsPanel" role="dialog" aria-modal="true" aria-labelledby="settings-title" onMouseDown={(e) => e.stopPropagation()}>
          <div className="settingsHead"><div><p className="sectionNote">Backend settings</p><h2 id="settings-title">Generation setup</h2></div>
            <button className="closeButton" onClick={() => setSettingsOpen(false)}>Close</button></div>
          <p className="settingsCopy">Current mode: {selection.mode === 'local' ? 'Ollama + Piper' : 'Gemini script + narration'}. Compute host: {runtime?.host || 'backend computer'}.</p>
          {runtime?.owner_settings ? <>
            <button className="secondary" onClick={savePreset}>Save current preset as default</button>
            {selection.mode === 'local' ? <>
              <p className="settingsCopy">Install Ollama and requirements-local.txt, then download a model and Piper voice during setup. See the repository's local setup guide for commands. Generation never downloads assets or switches to a cloud service.</p>
              {providers?.ollama?.recovery_required && <div className="notice error"><span>A previous inference may still be running. Restart your dedicated Ollama runtime first.</span>
                <button type="button" onClick={confirmRuntimeRestart} disabled={busy}>I restarted Ollama</button></div>}
            </> : <>
              <div className="settingStatus"><span className={`keyDot ${apiKeyConfigured ? 'configured' : ''}`} aria-hidden="true" />{apiKeyConfigured ? 'A Gemini key is saved' : 'No Gemini key is saved'}</div>
              <p className="settingsCopy">Gemini receives your prompt and narration. The key is saved in the backend's .env file and is never returned in API responses.</p>
              <form className="settingsForm" onSubmit={saveApiKey}>
                <label htmlFor="api-key">{apiKeyConfigured ? 'Replace API key' : 'API key'}</label>
                <div className="keyField"><input id="api-key" type={showApiKey ? 'text' : 'password'} value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                  minLength="10" maxLength="512" autoComplete="off" spellCheck="false" placeholder="Paste a Gemini API key" />
                  <button type="button" onClick={() => setShowApiKey((value) => !value)}>{showApiKey ? 'Hide' : 'Show'}</button></div>
                <div className="settingsActions"><button className="primary" type="submit" disabled={savingKey || apiKey.trim().length < 10}>{savingKey ? 'Saving…' : 'Save key'}</button></div>
              </form>
            </>}
          </> : <p className="settingsCopy">Settings changes and key management are available only from a loopback session on the backend computer.</p>}
          {settingsMessage && <p className="settingsMessage" role="status">{settingsMessage}</p>}
        </section>
      </div>}
    </main>
  )
}
