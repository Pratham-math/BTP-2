import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, post } from '../platform/api'
import { Badge, Empty, JobView, Notice, PageHead, useResource } from '../platform/common'
import { useAuth } from '../platform/auth'

export function Library() {
  const { profile } = useAuth(), lessons = useResource('/api/lessons', 5000), sessions = useResource('/api/sessions'), jobs = useResource('/api/jobs', 5000)
  return <><PageHead eyebrow="INDEPENDENT STUDY" title={`A little further, ${profile.display_name.split(' ')[0]}.`} action={<Link className="button" to="/lessons/new">+ Create a lesson</Link>}>Turn your material into a complete learning path. Learn at your pace, then put it into practice.</PageHead>
    <section className="study-banner"><div><Badge>Your next connection</Badge><h2>Go from “I’ve seen it”<br />to “I understand it.”</h2><p>Start with a source. Explore a visual explanation.<br />Check your understanding, one concept at a time.</p><Link to="/sources">Add learning material <span aria-hidden="true">↗</span></Link></div><div className="banner-steps" aria-hidden="true"><span>01 — SOURCE</span><i /><span>02 — UNDERSTAND</span><i /><span>03 — PRACTICE</span></div></section>
    {sessions.data?.length > 0 && <section><div className="section-head"><h2>Pick up where you left off</h2><Link to="/progress">View progress ↗</Link></div><div className="card-grid">{sessions.data.slice(0, 3).map(x => <Link className="lesson-card" key={x.id} to={`/learn/${x.id}`}><Badge>{x.state}</Badge><h3>{x.title}</h3><p>{x.objective_id}</p><span className="card-link">Resume learning ↗</span></Link>)}</div></section>}
    <section><div className="section-head"><h2>Your lesson library</h2><span className="muted">{lessons.data?.filter(x => !x.course_id).length || 0} lessons</span></div><Notice error>{lessons.error}</Notice>
      {lessons.data?.filter(x => !x.course_id).length ? <div className="card-grid">{lessons.data.filter(x => !x.course_id).map(x => <article className="lesson-card" key={x.id}><Badge>{x.availability}</Badge><h3>{x.title}</h3><p>Private independent study</p>{x.curriculum_id ? <Link className="card-link" to={`/lessons/${x.curriculum_id}`}>Open learning path ↗</Link> : <p className="muted">The curriculum is being prepared.</p>}</article>)}</div> : <Empty title="Your next lesson starts here">Add notes or a topic, confirm the source preview, then build a learning path.</Empty>}
    </section>{jobs.data?.length > 0 && <section><div className="section-head"><h2>Preparation queue</h2></div><div className="list">{jobs.data.slice(0, 8).map(x => <Link className="list-row" key={x.id} to={`/jobs/${x.id}`}><strong>{x.kind.replaceAll('_', ' ')}</strong><span>{x.stage.replaceAll('_', ' ')}</span><Badge>{x.state}</Badge></Link>)}</div></section>}</>
}

export function SourcesPage() {
  const { config } = useAuth(), features = config?.source_features || { text: true }
  const { data, error, reload } = useResource('/api/sources'), [kind, setKind] = useState('text'), [title, setTitle] = useState(''), [text, setText] = useState('')
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), navigate = useNavigate()
  async function create(event) { event.preventDefault(); setBusy(true); setMessage('')
    try { const source = await post('/api/sources', { title, kind, text }); navigate(`/sources/${source.id}`) } catch (e) { setMessage(e.message) } finally { setBusy(false) } }
  async function upload(event) { const file = event.target.files?.[0]; if (!file) return; setBusy(true); setMessage('')
    try { const body = new FormData(); body.append('file', file); const source = await api('/api/sources/upload', { method: 'POST', body }); navigate(`/sources/${source.id}`) } catch (e) { setMessage(e.message) } finally { setBusy(false) } }
  return <><PageHead eyebrow="SOURCE LIBRARY" title="Start with something worth learning.">Your original material and corrections stay attached to the lesson.</PageHead><div className="two-columns"><form className="panel form" onSubmit={create}><h2>Add a source</h2><label>Source type<select value={kind} onChange={e => setKind(e.target.value)}><option value="text">Typed or pasted notes</option>{features.topic && <option value="topic">Topic · official Python collection</option>}{features.youtube && <option value="youtube">Public YouTube video</option>}</select></label><label>Title<input required minLength={3} maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label><label>{kind === 'youtube' ? 'Public video URL' : kind === 'topic' ? 'What do you want to study?' : 'Source text'}<textarea required minLength={3} maxLength={250000} rows={8} value={text} onChange={e => setText(e.target.value)} spellCheck={false} /></label><button disabled={busy}>{busy ? 'Adding source…' : 'Create source preview'}</button><Notice error>{message}</Notice></form>
    <div><section className="panel upload-panel"><h2>Bring your material</h2>{features.document || features.image ? <><p>Extraction warnings require your review against the uploaded original.</p><label className="file-button">Choose source file<input type="file" accept={[features.document && '.pdf,.pptx,.ppt', features.image && '.png,.jpg,.jpeg'].filter(Boolean).join(',')} disabled={busy} onChange={upload} /></label><p className="muted">Up to 25 MB. Long sources use explicit batches.</p></> : <p>Document and image uploads are not enabled yet. Their storage, isolation and extraction checks must pass first. You can add corrected text notes now.</p>}</section><h2 className="spaced">Saved sources</h2><Notice error>{error}</Notice><div className="list">{data?.map(x => <Link className="list-row" key={x.id} to={`/sources/${x.id}`}><strong>{x.title}</strong><Badge>{x.state}</Badge></Link>)}</div>{data?.length === 0 && <Empty title="No sources yet">Add a source to begin.</Empty>}</div></div></>
}

function SourceImage({ sourceId, block }) {
  const [visible, setVisible] = useState(false)
  const preview = useResource(visible ? `/api/sources/${sourceId}/evidence/${block.id}/image` : null, 240000)
  if (!block.image_key) return null
  return <aside className="source-image"><button className="secondary" onClick={() => setVisible(value => !value)}>{visible ? 'Hide page image' : 'Compare original page image'}</button>
    {visible && <><Notice error>{preview.error}</Notice>{preview.data ? <img src={preview.data.url} alt={`Source reference for ${block.location}. Check its text, notation and diagrams against the extracted evidence.`} loading="lazy" referrerPolicy="no-referrer" /> : !preview.error && <p>Opening a private page preview…</p>}<p className="muted">A rendered page is a source reference, not an automatically verified interpretation.</p></>}
  </aside>
}

export function SourceDetail() {
  const { id } = useParams(), source = useResource(`/api/sources/${id}`, 5000), [evidence, setEvidence] = useState(null), [message, setMessage] = useState(''), [busy, setBusy] = useState(false)
  const loadedVersion = useRef(null), dirty = useRef(false)
  useEffect(() => { loadedVersion.current = null; dirty.current = false; setEvidence(null) }, [id])
  useEffect(() => { if (source.data && source.data.id === id && !dirty.current && loadedVersion.current !== source.data.version) { setEvidence(source.data.evidence); loadedVersion.current = source.data.version } }, [source.data, id])
  function editEvidence(value) { dirty.current = true; setEvidence(value) }
  async function save(confirm) { setBusy(true); setMessage('')
    try { const value = await api(`/api/sources/${id}/preview`, { method: 'PUT', body: JSON.stringify({ expected_version: loadedVersion.current, evidence, confirm, note: 'Author checked the source and saved this extraction revision.' }) }); dirty.current = false; loadedVersion.current = value.version; setEvidence(value.evidence); source.reload(); setMessage(confirm ? 'Source confirmed. You can use it in a lesson.' : 'Saved a correction revision.') } catch (e) { setMessage(e.message) } finally { setBusy(false) } }
  async function original() { try { const { url } = await api(`/api/sources/${id}/original`); window.open(url, '_blank', 'noopener,noreferrer') } catch (e) { setMessage(e.message) } }
  const data = source.data
  if (!data) return <Notice error={!!source.error}>{source.error || 'Loading source…'}</Notice>
  return <><PageHead eyebrow="SOURCE PREVIEW" title={data.title} action={<Badge>{data.state}</Badge>}>Check code indentation, numbers, units, and diagram relationships against the original. Confirmation creates a new source version.</PageHead><Notice>{message}</Notice>
    <div className="row">{data.has_original && <button className="secondary" onClick={original}>Open uploaded original</button>}{data.confirmed && <Link className="button" to="/lessons/new">Use in a lesson ↗</Link>}</div>
    {data.job_id && !data.evidence.length && <JobView id={data.job_id} />}
    {(evidence || []).map((block, index) => <section className="panel source-block" key={block.id}><div className="row"><h2>{block.location}</h2><Badge>{block.method}</Badge></div><textarea rows={Math.min(16, Math.max(5, block.text.split('\n').length))} value={block.text} spellCheck={false} onChange={e => editEvidence(evidence.map((x, i) => i === index ? { ...x, text: e.target.value } : x))} />
      <SourceImage sourceId={id} block={block} />
      {block.uncertainty.length > 0 && <><Notice error>{block.uncertainty.join(' · ')}</Notice><label className="check-label"><input type="checkbox" checked={false} onChange={() => editEvidence(evidence.map((x, i) => i === index ? { ...x, uncertainty: [] } : x))} />I corrected this block using the original and verified its uncertain symbols.</label></>}
    </section>)}{evidence?.length > 0 && <div className="row"><button className="secondary" disabled={busy} onClick={() => save(false)}>Save corrections</button><button disabled={busy || evidence.some(x => x.uncertainty.length)} onClick={() => save(true)}>Confirm source for lessons</button></div>}</>
}

export function NewLesson() {
  const sources = useResource('/api/sources'), [search] = useSearchParams(), navigate = useNavigate(), [selected, setSelected] = useState([])
  const [title, setTitle] = useState(''), [goal, setGoal] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  async function submit(event) { event.preventDefault(); setBusy(true); setError('')
    try { const lesson = await post('/api/lessons', { title, goal, source_ids: selected, course_id: search.get('course') }); navigate(`/jobs/${lesson.job_id}`) } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <><PageHead eyebrow={search.get('course') ? 'CLASSROOM DRAFT' : 'NEW INDEPENDENT LESSON'} title="Give your learning a clear direction.">The complete objective and assessment plan comes first. You will confirm the scope before video preparation.</PageHead><form className="panel form narrow" onSubmit={submit}><label>Lesson title<input required minLength={3} maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label><label>Your learning goal<textarea required minLength={10} maxLength={6000} rows={4} value={goal} onChange={e => setGoal(e.target.value)} placeholder="For example: understand how Python loops traverse a list, trace index boundaries, and write a search function." /></label>
    <fieldset><legend>Confirmed sources</legend>{sources.data?.filter(x => x.state === 'confirmed').map(x => <label className="check-label" key={x.id}><input type="checkbox" checked={selected.includes(x.id)} onChange={e => setSelected(e.target.checked ? [...selected, x.id] : selected.filter(id => id !== x.id))} />{x.title}</label>)}{!sources.data?.some(x => x.state === 'confirmed') && <p><Link to="/sources">Add and confirm a source</Link> before planning a lesson.</p>}</fieldset><Notice error>{error || sources.error}</Notice><button disabled={busy || !selected.length}>{busy ? 'Queuing curriculum…' : 'Plan the full curriculum'}</button></form></>
}

export function LessonDetail() {
  const { id } = useParams(), lesson = useResource(`/api/lessons/versions/${id}`, 5000), navigate = useNavigate(), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  async function action(kind) { setBusy(true); setError(''); try {
    if (kind === 'start') { const result = await post('/api/sessions', { curriculum_id: id }); navigate(`/learn/${result.id}`) }
    else { const result = await post(`/api/lessons/versions/${id}/${kind}`, kind === 'confirm' ? { expected_fingerprint: lesson.data.fingerprint } : undefined); navigate(`/jobs/${result.job_id}`) }
  } catch (e) { setError(e.message) } finally { setBusy(false) } }
  const data = lesson.data
  if (!data) return <Notice error={!!lesson.error}>{lesson.error || 'Loading curriculum…'}</Notice>
  return <><PageHead eyebrow={data.course_id ? 'CLASSROOM LESSON' : 'INDEPENDENT STUDY'} title={data.title} action={<Badge>{data.availability}</Badge>}>{data.blueprint.scope}</PageHead><Notice error>{error}</Notice><div className="row"><Badge>{data.publication}</Badge><Badge>{data.confirmed ? 'Scope confirmed' : 'Scope awaits confirmation'}</Badge><span className="muted">{data.blueprint.objectives.length} required objectives · version {data.number}</span></div>
    {data.blueprint.source_coverage?.length > 0 && <details className="panel"><summary>Source coverage · {data.blueprint.planning_batches || 1} planning batches</summary><p>Every selected section is included below or explicitly excluded. Review exclusions before confirming the scope.</p>{data.blueprint.source_coverage.map(entry => <div className="list-row" key={`${entry.source_version_id}:${entry.block_id}`}><strong>{entry.block_id}</strong><span>{entry.exclusion_reason || `Included in: ${entry.objective_ids.join(', ')}`}</span></div>)}</details>}
    <div className="two-columns"><section><h2 className="spaced">Your complete learning path</h2><ol className="objective-list">{data.blueprint.objectives.map((obj, index) => <li key={obj.id}><span className="objective-number">{String(index + 1).padStart(2, '0')}</span><div><h3>{obj.title}</h3><p>{obj.description}</p><small>{data.blocks.filter(x => x.objective_id === obj.id).map(x => `${x.profile}: ${x.state}`).join(' · ')}</small></div></li>)}</ol></section><aside className="panel"><h2>Before you begin</h2><p>A prepared first block includes the explanation, common recap, hints, and validated checkpoints. Later independent blocks may still be preparing.</p>{data.blueprint.prerequisites?.map((x, i) => <p key={i}>↳ {x}</p>)}
      {!data.confirmed && <button disabled={busy} onClick={() => action('confirm')}>Confirm scope and prepare</button>}{data.confirmed && !data.course_id && <button disabled={busy || !['ready', 'playable_partial'].includes(data.availability)} onClick={() => action('start')}>Start learning ↗</button>}
      {data.confirmed && data.publication === 'draft' && <button className="secondary" disabled={busy} onClick={() => action('prepare')}>Prepare remaining blocks</button>}{data.course_id && <Link className="button secondary" to={`/reviews/${id}`}>Review classroom version</Link>}<p className="muted">Automated validation is separate from teacher approval.</p></aside></div></>
}

export function ProgressPage() {
  const reports = useResource('/api/reports/me'), sessions = useResource('/api/sessions')
  return <><PageHead eyebrow="YOUR PROGRESS" title="See what is taking shape.">Viewed, passed, assisted, and unresolved objectives are recorded separately.</PageHead><Notice error>{reports.error}</Notice>{reports.data?.map(item => <section className="panel" key={item.id}><div className="row"><h2>{sessions.data?.find(x => x.id === item.id)?.title || 'Learning session'}</h2><Badge>{item.state}</Badge></div><div className="evidence-grid">{Object.entries(item.evidence).map(([id, value]) => <div key={id}><strong>{id}</strong><Badge>{value.status || 'viewed'}</Badge><p>{value.attempts || 0} attempts · {value.hints_used || 0} hints</p></div>)}</div><Link to={`/learn/${item.id}`}>Resume session ↗</Link></section>)}{reports.data?.length === 0 && <Empty title="Your progress will grow here">Start a lesson to record your first objective.</Empty>}</>
}
