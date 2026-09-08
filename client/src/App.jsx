import { useEffect, useState } from 'react'

const samplePrompt = 'Explain how photosynthesis turns sunlight into stored chemical energy for a high-school student.'

export default function App() {
  const [prompt, setPrompt] = useState('')
  const [job, setJob] = useState(null)
  const [recent, setRecent] = useState([])
  const [error, setError] = useState('')
  const busy = job && ['queued', 'running'].includes(job.state)

  useEffect(() => {
    loadRecent()
  }, [])

  useEffect(() => {
    if (!busy) return
    const timer = setInterval(() => refreshJob(job.id), 1800)
    return () => clearInterval(timer)
  }, [job?.id, job?.state])

  async function loadRecent() {
    try {
      const response = await fetch('/api/videos')
      if (response.ok) setRecent(await response.json())
    } catch {
      // The main action will show a useful server error if the backend is offline.
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

  return (
    <main>
      <nav>
        <a className="brand" href="/" aria-label="LearnFrame home">
          <span className="brandMark">L</span>
          <span>LearnFrame</span>
        </a>
        <span className="badge"><i /> Gemini + FFmpeg</span>
      </nav>

      <section className="hero">
        <p className="eyebrow">PROMPT → NARRATED VIDEO</p>
        <h1>Turn an idea into a<br /><em>lesson you can watch.</em></h1>
        <p className="intro">Describe what you want to learn. Gemini writes and narrates a three-slide lesson, then FFmpeg packages it as one video.</p>
      </section>

      <section className="workspace">
        <form onSubmit={createVideo}>
          <div className="fieldHead">
            <label htmlFor="prompt">What should the lesson explain?</label>
            <span>{prompt.length} / 2000</span>
          </div>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            maxLength="2000"
            placeholder="Try: Explain gradient descent with a simple hill analogy..."
            disabled={busy}
          />
          <div className="formFooter">
            <button className="suggestion" type="button" onClick={() => setPrompt(samplePrompt)} disabled={busy}>
              Use an example
            </button>
            <button className="primary" type="submit" disabled={busy || prompt.trim().length < 3}>
              {busy ? 'Creating video…' : 'Generate lesson'} <span>→</span>
            </button>
          </div>
        </form>

        {error && <div className="notice error" role="alert">{error}</div>}

        {job && (
          <article className="result">
            {busy && (
              <div className="status">
                <div className="spinner" />
                <div>
                  <p className="statusTitle">{job.stage}</p>
                  <p>Gemini calls can take a few minutes. You can leave this tab open.</p>
                </div>
                <strong>{Math.round(((job.current || 0) / (job.total || 3)) * 100)}%</strong>
              </div>
            )}

            {job.state === 'failed' && (
              <div className="failed">
                <p className="statusTitle">Generation stopped</p>
                <p>{job.error}</p>
                <button className="secondary" onClick={retry}>Retry</button>
              </div>
            )}

            {job.state === 'ready' && (
              <div className="ready">
                <div className="readyHead">
                  <div>
                    <p className="eyebrow">YOUR LESSON IS READY</p>
                    <h2>{job.title || 'Generated lesson'}</h2>
                  </div>
                  <a className="download" href={`/api/videos/${job.id}/download`}>Download MP4 ↓</a>
                </div>
                <video
                  key={job.id}
                  controls
                  preload="metadata"
                  src={`/api/videos/${job.id}/file`}
                  onLoadedMetadata={enableAudio}
                  onPlay={enableAudio}
                />
                <p className="audioNote">🔊 Narration included · If silent, right-click the Chrome tab and choose “Unmute site”.</p>
              </div>
            )}
          </article>
        )}
      </section>

      {recent.length > 0 && !busy && (
        <section className="recent">
          <p className="eyebrow">RECENT GENERATIONS</p>
          <div className="recentList">
            {recent.map((item) => (
              <button key={item.id} onClick={() => setJob(item)}>
                <span>{item.title || 'Untitled lesson'}</span>
                <small>{item.state}</small>
              </button>
            ))}
          </div>
        </section>
      )}

      <footer>Local prototype · Your API key stays on the server</footer>
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
