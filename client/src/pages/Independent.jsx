import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { LessonOptions } from '../platform/actions'
import { api, post } from '../platform/api'
import { Badge, Empty, JobCard, Notice, PageHead, useResource } from '../platform/common'

export { SourcesPage, SourceDetail } from './Sources'

export { Library } from './StudyWorkspace'

function QuickLesson() {
  const navigate = useNavigate(), [form, setForm] = useState({ title: '', prompt: '', notes: '', reference: true }), [files, setFiles] = useState([])
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const field = key => e => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    const body = new FormData()
    Object.entries(form).forEach(([k, v]) => body.append(k, v)); files.forEach(f => body.append('files', f))
    try { const lesson = await api('/api/lessons/quick', { method: 'POST', body }); navigate(`/jobs/${lesson.job_id}`) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <><PageHead eyebrow="NEW LESSON" title="What do you want to learn?">Describe it in your own words, and add your notes, PDFs or slides if you have them. We build a full learning path with videos and checks.</PageHead>
    <form className="panel form narrow" onSubmit={submit}>
      <label>Topic<input required minLength={3} maxLength={160} value={form.title} onChange={field('title')} placeholder="e.g. Binary search" /></label>
      <label>What should you be able to do afterwards?<textarea required minLength={10} maxLength={6000} rows={3} value={form.prompt} onChange={field('prompt')} placeholder="e.g. Understand how binary search halves a sorted list, why it is O(log n), and write it in Python." /></label>
      <p><Link to="/lessons/new?mode=sources">Use saved sources or a YouTube extraction</Link></p><label>Your notes (optional)<textarea rows={5} maxLength={250000} value={form.notes} onChange={field('notes')} placeholder="Paste lecture notes, definitions or code here." /></label>
      <label>Slides or documents (optional, up to 5)<input type="file" multiple accept=".pdf,.pptx" disabled={busy} onChange={e => { setFiles([...e.target.files].slice(0, 5)); e.target.value = '' }} /></label>
      <ul>{files.map((file, index) => <li key={`${file.name}:${index}`}>{file.name} <button type="button" className="secondary" disabled={busy} aria-label={`Remove file ${file.name}`} onClick={() => setFiles(files.filter((_, i) => i !== index))}>Remove</button></li>)}</ul>
      <label className="check-label"><input type="checkbox" checked={form.reference} onChange={field('reference')} />Also use a reference article on this topic</label>
      <Notice error>{error}</Notice>
      <button disabled={busy}>{busy ? 'Uploading…' : 'Build my lesson'}</button>
      <p className="muted">Follow the preparation page for a live status and estimated generation time. You can leave and come back.</p>
    </form></>
}

export function NewLesson() {
  const [params] = useSearchParams()
  return params.get('course') || params.get('source') || params.get('mode') === 'sources' ? <PlannedLesson /> : <QuickLesson />
}

function PlannedLesson() {
  const sources = useResource('/api/sources'), [search] = useSearchParams(), navigate = useNavigate(), [selected, setSelected] = useState(() => [...new Set(search.getAll('source'))].slice(0, 20))
  const [title, setTitle] = useState(''), [goal, setGoal] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  async function submit(event) { event.preventDefault(); setBusy(true); setError('')
    try { const lesson = await post('/api/lessons', { title, goal, source_ids: selected, course_id: search.get('course') }); navigate(`/jobs/${lesson.job_id}`) } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <><PageHead eyebrow={search.get('course') ? 'CLASSROOM DRAFT' : 'NEW INDEPENDENT LESSON'} title="Give your learning a clear direction.">The complete objective and assessment plan comes first. You will confirm the scope before video preparation.</PageHead><form className="panel form narrow" onSubmit={submit}><label>Lesson title<input required minLength={3} maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label><label>Your learning goal<textarea required minLength={10} maxLength={6000} rows={4} value={goal} onChange={e => setGoal(e.target.value)} placeholder="For example: understand how Python loops traverse a list, trace index boundaries, and write a search function." /></label>
    <fieldset><legend>Confirmed sources</legend>{sources.data?.filter(x => x.state === 'confirmed').map(x => <label className="check-label" key={x.id}><input type="checkbox" checked={selected.includes(x.id)} onChange={e => setSelected(e.target.checked ? [...selected, x.id] : selected.filter(id => id !== x.id))} />{x.title}</label>)}{!sources.data?.some(x => x.state === 'confirmed') && <p><Link to="/sources">Add and confirm a source</Link> before planning a lesson.</p>}</fieldset><Notice error>{error || sources.error}</Notice><button disabled={busy || !selected.length}>{busy ? 'Queuing curriculum…' : 'Plan the full curriculum'}</button></form></>
}

export function LessonDetail() {
  const jobs = useResource('/api/jobs', 5000)
  const { id } = useParams(), lesson = useResource(`/api/lessons/versions/${id}`, 5000), navigate = useNavigate(), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  async function action(kind) { setBusy(true); setError(''); try {
    if (kind === 'start') { const result = await post('/api/sessions', { curriculum_id: id }); navigate(`/learn/${result.id}`) }
    else { const result = await post(`/api/lessons/versions/${id}/${kind}`, kind === 'confirm' ? { expected_fingerprint: lesson.data.fingerprint } : undefined); navigate(`/jobs/${result.job_id}`) }
  } catch (e) { setError(e.message) } finally { setBusy(false) } }
  const data = lesson.data
  if (!data) return <Notice error={!!lesson.error}>{lesson.error || 'Loading curriculum…'}</Notice>
  return <><PageHead eyebrow={data.course_id ? 'CLASSROOM LESSON' : 'INDEPENDENT STUDY'} title={data.title} action={<div className="row"><Badge>{data.availability}</Badge>{data.can_manage && <LessonOptions lesson={data} onDeleted={() => navigate(data.course_id ? `/classroom/${data.course_id}` : '/')} />}</div>}>{data.blueprint.scope}</PageHead><Notice error>{error}</Notice><div className="row"><Badge>{data.publication}</Badge><Badge>{data.confirmed ? 'Scope confirmed' : 'Scope awaits confirmation'}</Badge><span className="muted">{data.blueprint.objectives.length} required objectives · version {data.number}</span></div>
    {data.blueprint.source_coverage?.length > 0 && <details className="panel"><summary>Source coverage · {data.blueprint.planning_batches || 1} planning batches</summary><p>Every selected section is included below or explicitly excluded. Review exclusions before confirming the scope.</p>{data.blueprint.source_coverage.map(entry => <div className="list-row" key={`${entry.source_version_id}:${entry.block_id}`}><strong>{entry.block_id}</strong><span>{entry.exclusion_reason || `Included in: ${entry.objective_ids.join(', ')}`}</span></div>)}</details>}
    <div className="card-grid">{jobs.data?.filter(x => x.lesson_id === data.lesson_id && ['queued', 'running', 'failed', 'waiting_for_input', 'waiting_for_review'].includes(x.state)).map(job => <JobCard job={job} key={job.id} />)}</div><div className="two-columns"><section><h2 className="spaced">Your complete learning path</h2><ol className="objective-list">{data.blueprint.objectives.map((obj, index) => <li key={obj.id}><span className="objective-number">{String(index + 1).padStart(2, '0')}</span><div><h3>{obj.title}</h3><p>{obj.description}</p><small>{data.blocks.filter(x => x.objective_id === obj.id).map(x => `${x.profile}: ${x.state}`).join(' · ')}</small></div></li>)}</ol></section><aside className="panel"><h2>Before you begin</h2><p>{data.course_id ? 'Prepare and review all required explanations, recaps and checkpoints before publishing this classroom version.' : 'Start with the first block while blocks 2 and 3 prepare normally. Your answer to assessment 1 shapes block 4, assessment 2 shapes block 5, and later explanations adapt in the background. Required concepts and checkpoints stay fixed.'}</p>{data.blueprint.prerequisites?.map((x, i) => <p key={i}>↳ {x}</p>)}
      {!data.confirmed && <button disabled={busy} onClick={() => action('confirm')}>Confirm scope and prepare</button>}{data.confirmed && !data.course_id && <button disabled={busy || !['ready', 'playable_partial'].includes(data.availability)} onClick={() => action('start')}>Start learning ↗</button>}
      {data.confirmed && data.publication === 'draft' && <button className="secondary" disabled={busy} onClick={() => action('prepare')}>{data.course_id ? 'Prepare remaining blocks' : 'Prepare initial three blocks'}</button>}{data.course_id && <Link className="button secondary" to={`/reviews/${id}`}>Review classroom version</Link>}<p className="muted">Automated validation is separate from teacher approval.</p></aside></div></>
}

export function ProgressPage() {
  const reports = useResource('/api/reports/me'), sessions = useResource('/api/sessions')
  return <><PageHead eyebrow="YOUR PROGRESS" title="See what is taking shape.">Viewed, passed, assisted, and unresolved objectives are recorded separately.</PageHead><Notice error>{reports.error}</Notice>{reports.data?.map(item => <section className="panel" key={item.id}><div className="row"><h2>{sessions.data?.find(x => x.id === item.id)?.title || 'Learning session'}</h2><Badge>{item.state}</Badge></div><div className="evidence-grid">{Object.entries(item.evidence).map(([id, value]) => <div key={id}><strong>{id}</strong><Badge>{value.status || 'viewed'}</Badge><p>{value.attempts || 0} attempts · {value.hints_used || 0} hints</p></div>)}</div><Link to={`/learn/${item.id}`}>Resume session ↗</Link></section>)}{reports.data?.length === 0 && <Empty title="Your progress will grow here">Start a lesson to record your first objective.</Empty>}</>
}
