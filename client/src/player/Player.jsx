import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { api, post } from '../platform/api'
import { useAuth } from '../platform/auth'
import { Badge, IssueReport, Notice, PageHead } from '../platform/common'
import { ScenePlayer } from '../remotion/ScenePlayer'
import { useTheme } from '../platform/theme'
import { AdaptiveStatus } from './AdaptiveStatus'

function Checkpoint({ session, onResult, checkpointAction }) {
  const { theme } = useTheme()
  const { profile, config } = useAuth(), question = session.question
  const draftKey = `btp2:${profile.id}:${session.id}:${question.id}:${session.route_revision}:code`
  const [choice, setChoice] = useState(''), [choices, setChoices] = useState([]), [output, setOutput] = useState(''), [text, setText] = useState('')
  const [code, setCode] = useState(() => localStorage.getItem(draftKey) ?? session.position.code_draft ?? question.starter_code ?? '')
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [hint, setHint] = useState(''), pending = useRef(null)
  const [draftStatus, setDraftStatus] = useState('Saved on this device'), savedCode = useRef(session.position.code_draft ?? question.starter_code ?? '')
  useEffect(() => {
    if (question.kind !== 'python' || busy || code === savedCode.current) return
    const timer = setTimeout(async () => {
      try { await checkpointAction('draft', { assessment_id: question.id, route_revision: session.route_revision, code }); savedCode.current = code; setDraftStatus('Draft saved to your account') }
      catch (e) { setDraftStatus('Saved on this device · account sync failed'); setError(e.message) }
    }, 1700)
    return () => clearTimeout(timer)
  }, [code, busy, checkpointAction, question.id, question.kind, session.route_revision])
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    const answer = question.kind === 'mcq' ? { choice } : question.kind === 'multiple' ? { choices } : question.kind === 'trace' ? { output } : question.kind === 'short' ? { text } : { code }
    const body = { session_id: session.id, assessment_id: question.id, route_revision: session.route_revision, expected_revision: session.revision, answer }
    const signature = JSON.stringify({ ...body, expected_revision: undefined })
    if (pending.current?.signature !== signature) pending.current = { signature, body: { ...body, idempotency_key: crypto.randomUUID().replaceAll('-', '') } }
    try { const result = await checkpointAction('submit', pending.current.body); pending.current = null; await onResult(result) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function getHint() { setBusy(true); setError(''); try { const result = await checkpointAction('hint'); setHint(result.hint) } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <section className="checkpoint panel" aria-labelledby="checkpoint-title"><div className="row"><p className="eyebrow">PAUSE & PRACTICE</p><Badge>{question.kind}</Badge></div><h2 id="checkpoint-title">Check your understanding</h2><p className="question-prompt">{question.prompt}</p><form onSubmit={submit}>
    {['mcq', 'multiple'].includes(question.kind) && <fieldset className="answer-options"><legend className="sr-only">Choose your answer</legend>{question.options.map(option => <label key={option.id} className="answer-option"><input type={question.kind === 'mcq' ? 'radio' : 'checkbox'} name="answer" checked={question.kind === 'mcq' ? choice === option.id : choices.includes(option.id)} onChange={e => question.kind === 'mcq' ? setChoice(option.id) : setChoices(e.target.checked ? [...choices, option.id] : choices.filter(x => x !== option.id))} />{option.text}</label>)}</fieldset>}
    {question.kind === 'short' && <label>Your answer<textarea rows={5} value={text} maxLength={4000} onChange={e => setText(e.target.value)} placeholder="Explain in your own words (2-4 sentences)." /></label>}
    {question.kind === 'trace' && <label>Predicted output<textarea rows={5} value={output} maxLength={16000} spellCheck={false} onChange={e => setOutput(e.target.value)} /></label>}
    {question.kind === 'python' && <><label id="code-label">Your Python solution</label><CodeMirror theme={theme} aria-labelledby="code-label" value={code} height="260px" extensions={[python()]} onChange={value => { setCode(value); localStorage.setItem(draftKey, value); setDraftStatus('Saving draft…') }} /><p className="muted" role="status">Standard-library Python · {config?.runner_mode === 'local_demo' ? 'local demo runner' : 'isolated runner'} · {draftStatus}.</p></>}
    {question.public_examples?.map((x, i) => <pre key={i}>Input: {x.stdin}{'\n'}Output: {x.stdout}</pre>)}<Notice error>{error}</Notice><Notice>{hint}</Notice>
    <div className="row"><button disabled={busy || (question.kind === 'mcq' && !choice) || (question.kind === 'multiple' && !choices.length) || (question.kind === 'short' && !text.trim())}>{busy ? 'Submitting…' : 'Check answer'}</button><button type="button" className="text-button" disabled={busy} onClick={getHint}>Give me a hint</button></div>
  </form></section>
}

export function Player() {
  const { id } = useParams(), [session, setSession] = useState(null), [error, setError] = useState(''), [feedback, setFeedback] = useState(null)
  const [attempt, setAttempt] = useState(null), [media, setMedia] = useState(null), [buffering, setBuffering] = useState(false), [speed, setSpeed] = useState(1), [fallback, setFallback] = useState(null)
  const latest = useRef(null), video = useRef(null), writeQueue = useRef(Promise.resolve()), lastSave = useRef(0), mediaOffset = useRef(0), continuing = useRef(false)
  const adopt = useCallback(value => { latest.current = value; setSession(value); if (value.last_attempt) { setAttempt(value.last_attempt); setFeedback(value.last_attempt.result) } }, [])
  const reload = useCallback(async () => { try { adopt(await api(`/api/sessions/${id}`)); setError('') } catch (e) { setError(e.message) } }, [id, adopt])
  useEffect(() => { setSession(null); setMedia(null); reload() }, [reload])
  const clipIndex = session?.position.clip || 0, clip = session?.clips[clipIndex]
  const checkpointAction = useCallback((kind, body = {}) => {
    const task = writeQueue.current.catch(() => {}).then(async () => {
      const current = latest.current
      if (!current || current.state !== 'checkpoint') throw new Error('Reload the selected checkpoint before saving.')
      if (kind === 'submit') {
        // Keep the same complete payload on an uncertain network retry. Draft
        // and hint writes admitted ahead of it supply the current revision.
        if (!body.revision_bound) { body.expected_revision = current.revision; body.revision_bound = true }
        const { revision_bound, ...payload } = body
        return post('/api/attempts', payload)
      }
      const result = await api(`/api/sessions/${id}/${kind}`, { method: kind === 'draft' ? 'PATCH' : 'POST', body: JSON.stringify({ ...body, expected_revision: current.revision }) })
      if (kind === 'draft') adopt(result); else adopt({ ...latest.current, revision: result.revision })
      return result
    })
    writeQueue.current = task
    return task
  }, [id, adopt])

  useEffect(() => {
    let active = true, nextElement = document.createElement('video')
    async function authorize() {
      if (!clip) { setMedia(null); return }
      try {
        const [asset, caption] = await Promise.all([api(`/api/assets/${clip.id}/access?session_id=${id}`), api(`/api/sessions/${id}/captions/${clip.id}`).catch(() => null)])
        if (!active) return
        mediaOffset.current = video.current?.currentTime || latest.current.position.offset || 0
        setMedia({ ...asset, caption: caption?.url, clipId: clip.id })
        const next = latest.current.clips[clipIndex + 1]
        if (next) { const signed = await api(`/api/assets/${next.id}/access?session_id=${id}`); if (active) { nextElement.preload = 'auto'; nextElement.src = signed.url; nextElement.load() } }
      } catch (e) { if (active) setError(e.message) }
    }
    setMedia(null); authorize()
    const refresh = setInterval(authorize, 240000)
    return () => { active = false; clearInterval(refresh); nextElement.removeAttribute('src'); nextElement.load(); nextElement = null }
  }, [clip?.id, id])

  function save(ended = false, at = null) {
    const snapshot = latest.current, currentTime = at ?? video.current?.currentTime ?? 0
    if (!snapshot || snapshot.state !== 'playing') return
    writeQueue.current = writeQueue.current.catch(() => {}).then(async () => {
      const current = latest.current
      if (snapshot.route_revision !== current.route_revision || snapshot.selected_block_id !== current.selected_block_id || snapshot.position.clip !== current.position.clip) return
      try {
        const value = await api(`/api/sessions/${id}/progress`, { method: 'PATCH', body: JSON.stringify({ expected_revision: current.revision,
          route_revision: current.route_revision, block_id: current.selected_block_id, clip: current.position.clip, offset: currentTime, ended }) })
        adopt(value)
      } catch (e) { video.current?.pause(); setError(e.message); if (e.status === 409) await reload() }
    })
    return writeQueue.current
  }

  useEffect(() => {
    if (session?.state !== 'waiting_for_block' && session?.state !== 'submitting') return
    let active = true
    const tick = async () => {
      try {
        if (latest.current.state === 'submitting') {
          const identifier = attempt?.id || latest.current.active_attempt_id
          if (identifier) {
            const result = await api(`/api/attempts/${identifier}`)
            if (active && ['graded', 'service_failed'].includes(result.state)) { setFeedback(result.result); setAttempt(result); await reload() }
          } else await reload()
        } else {
          const next = await api(`/api/sessions/${id}/continuation`)
          if (active) adopt(next.session)
        }
      } catch (e) { if (active) setError(e.message) }
    }
    const timer = setInterval(tick, 1800); tick()
    return () => { active = false; clearInterval(timer) }
  }, [id, session?.state, attempt?.id, reload, adopt])

  async function result(value) { setAttempt(value); setFeedback(value.result); await reload() }
  async function revision(prerequisite_id = null) { try { adopt(await post(`/api/sessions/${id}/revision-route`, { expected_revision: latest.current.revision, prerequisite_id })); setFeedback(null) } catch (e) { setError(e.message) } }
  async function retryGrade() { try { setAttempt(await post(`/api/attempts/${attempt.id}/retry`)); await reload() } catch (e) { setError(e.message) } }
  async function showFallback() { try { const value = await api(`/api/sessions/${id}/fallback`); setFallback(value) } catch (e) { setError(e.message) } }
  async function resumeContinuation() { try { adopt(await post(`/api/sessions/${id}/resume-continuation`, { expected_revision: session.revision })); setError('') } catch (e) { setError(e.message) } }
  if (!session) return <Notice error={!!error}>{error || 'Restoring your learning session…'}</Notice>
  const objective = session.objectives.find(x => x.id === session.objective_id)
  const reviewing = session.objectives.find(x => x.id === session.position.reviewing_prerequisite)
  return <><PageHead eyebrow="YOUR LEARNING PATH" title={reviewing ? `Prerequisite review: ${reviewing.title}` : objective?.title || 'Learning session'} action={<Badge>{session.state}</Badge>}>{reviewing ? `You will return to ${objective.title} after this recap. No repeated prerequisite quiz is required.` : 'Progress is saved at scene boundaries and checkpoints.'}</PageHead><Notice error>{error}</Notice><div className="player-layout"><section><AdaptiveStatus adaptivity={session.adaptivity} objectiveId={session.objective_id} />
    {feedback?.feedback && <section className="feedback"><Badge>{feedback.passed ? 'Check passed' : 'Feedback'}</Badge><p>{feedback.feedback}</p>{feedback.objective_status && <Badge>{feedback.objective_status}</Badge>}{feedback.worked_solution && <p>{feedback.worked_solution}</p>}{feedback.reference_solution && <pre>{feedback.reference_solution}</pre>}{attempt?.state === 'service_failed' && <button onClick={retryGrade}>Retry grading saved code</button>}</section>}
    {session.state === 'playing' && <section className="video-panel">{media?.clipId === clip?.id && clip?.scene && clip.mime?.startsWith('audio') ? <ScenePlayer key={media.clipId}
      scene={clip.scene} audioUrl={media.url} captionUrl={media.caption} duration={clip.duration} index={clipIndex} total={session.clips.length}
      startAt={mediaOffset.current} speed={speed} autoPlay={continuing.current} onProgress={t => save(false, t)} onEnded={t => { continuing.current = true; save(true, t) }} />
      : media?.clipId === clip?.id ? <video key={media.clipId} ref={video} controls crossOrigin="anonymous" preload="auto" src={media.url}
      onLoadedMetadata={() => { if (video.current) { video.current.currentTime = mediaOffset.current; video.current.playbackRate = speed } }}
      onWaiting={() => setBuffering(true)} onCanPlay={() => setBuffering(false)} onPlaying={() => setBuffering(false)} onPause={() => save()}
      onTimeUpdate={() => { if (Date.now() - lastSave.current > 5000) { lastSave.current = Date.now(); save() } }} onEnded={() => save(true)}
      onError={() => setError('The clip could not load. Your progress is saved. Retry to renew its media link.')}>{media.caption && <track key={media.caption} kind="captions" src={media.caption} srcLang="en" label="English" />}</video> : <div className="media-loading">Authorizing this scene…</div>}
      <div className="player-controls"><span>Scene {clipIndex + 1} of {session.clips.length}{buffering ? ' · Buffering…' : ''}</span><label>Speed<select value={speed} onChange={e => { const speed = Number(e.target.value); setSpeed(speed); if (video.current) video.current.playbackRate = speed }}>{[.75, 1, 1.25, 1.5, 2].map(x => <option value={x} key={x}>{x}×</option>)}</select></label></div>
      <details className="transcript"><summary>Scene transcript</summary><p>{clip?.transcript}</p></details></section>}
    {session.state === 'checkpoint' && session.question && <Checkpoint key={session.question.id} session={session} onResult={result} checkpointAction={checkpointAction} />}
    {session.state === 'submitting' && <section className="panel waiting" role="status"><div className="spinner" /><h2>Checking your answer</h2><p>Your answer is saved. Grading code or a written answer can take a little while.</p></section>}
    {['waiting_for_block', 'preparing', 'recoverable_error'].includes(session.state) && <section className="panel waiting" role="status"><h2>{session.state === 'recoverable_error' ? 'This continuation needs attention' : 'Preparing the next explanation'}</h2><p>New narration and visuals take time. You can return later without losing confirmed progress.</p><div className="row"><button className="secondary" onClick={showFallback}>Review a relevant recap</button><button className="text-button" onClick={reload}>Check again</button>{session.state === 'recoverable_error' && <button onClick={resumeContinuation}>Retry selected continuation</button>}</div><Link to="/">Save and return to your library ↗</Link></section>}
    {fallback && <section className="panel"><div className="row"><h2>Optional recap · {objective?.title}</h2><button className="text-button" onClick={() => setFallback(null)}>Close recap</button></div>{fallback.clips.map((x, i) => x.scene && x.mime?.startsWith('audio') ? <ScenePlayer key={x.id} scene={x.scene} audioUrl={x.url} captionUrl={x.caption} duration={x.duration} index={i} total={fallback.clips.length} speed={speed} />
      : <video key={x.id} controls preload="metadata" crossOrigin="anonymous" src={x.url} />)}</section>}
    {session.state === 'needs_revision' && <section className="panel"><h2>Take a revision route</h2><p>The unresolved objective stays visible. Review the worked example and retry when you are ready.</p><button onClick={() => revision()}>Review concept and retry</button>{objective.prerequisites?.map(identifier => <button className="secondary" key={identifier} onClick={() => revision(identifier)}>Review prerequisite: {session.objectives.find(x => x.id === identifier)?.title}</button>)}</section>}
    {['complete', 'complete_with_support'].includes(session.state) && <section className="panel completion"><span aria-hidden="true">✓</span><h2>{session.state === 'complete' ? 'Your required objectives are complete.' : 'Lesson completed with support.'}</h2><p>{session.state === 'complete' ? 'Your explanations and required checks are recorded.' : 'Assisted objectives stay identified in your progress. They are not recorded as unassisted passes.'}</p><Link className="button" to="/progress">See your progress ↗</Link></section>}
  </section><aside className="panel path-sidebar"><h2>Complete objective map</h2><ol>{session.objectives.map(x => <li key={x.id} className={x.id === session.objective_id ? 'current' : ''}><strong>{x.title}</strong><Badge>{session.evidence[x.id]?.status || (session.evidence[x.id]?.viewed ? 'viewed' : 'required')}</Badge></li>)}</ol><p className="muted">Viewing is separate from passing. Every required concept remains in your path.</p><IssueReport curriculumId={session.curriculum_id} context={`Objective ${session.objective_id}; session ${session.id}`} /></aside></div></>
}
