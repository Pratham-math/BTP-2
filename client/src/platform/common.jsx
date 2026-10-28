import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from './api'
export function Notice({ children, error = false }) { return children ? <div className={`notice ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}>{children}</div> : null }
export function Badge({ children }) { return <span className="badge">{String(children || '').replaceAll('_', ' ')}</span> }
export function Empty({ title, children }) { return <div className="empty"><span aria-hidden="true">↗</span><h3>{title}</h3><p>{children}</p></div> }
export function IssueReport({ curriculumId, context }) {
  const [category, setCategory] = useState('content'), [description, setDescription] = useState(''), [message, setMessage] = useState(''), [busy, setBusy] = useState(false)
  async function report(event) { event.preventDefault(); setBusy(true); setMessage(''); try { await post('/api/issues', { curriculum_id: curriculumId, category, description: `${context}\n${description}` }); setDescription(''); setMessage('Report saved. Your confirmed progress is unchanged.') } catch (e) { setMessage(e.message) } finally { setBusy(false) } }
  return <details className="spaced"><summary>Report a problem with this lesson</summary><form className="form" onSubmit={report}><label>Problem type<select value={category} onChange={e => setCategory(e.target.value)}>{['content', 'assessment', 'accessibility', 'playback'].map(x => <option key={x} value={x}>{x}</option>)}</select></label><label>What should be checked?<textarea required minLength={10} maxLength={4500} rows={4} value={description} onChange={e => setDescription(e.target.value)} /></label><button disabled={busy}>{busy ? 'Saving…' : 'Send report'}</button><Notice>{message}</Notice></form></details>
}
export function PageHead({ eyebrow, title, children, action }) { return <div className="page-head"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <p className="page-intro">{children}</p>}</div>{action}</div> }
export function useResource(path, interval = 0) {
  const [data, setData] = useState(null), [error, setError] = useState(''), [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true, busy = false
    setData(null); setError('')
    const load = async () => { if (busy || !path) return; busy = true
      try { const value = await api(path); if (active) { setData(value); setError('') } } catch (error) { if (active) setError(error.message) } finally { busy = false } }
    load(); const timer = interval ? setInterval(load, interval) : null
    return () => { active = false; clearInterval(timer) }
  }, [path, interval, refresh])
  return { data, error, reload: () => setRefresh(x => x + 1) }
}
// Saved stage names -> what the learner should read.
const STAGES = [[/^audit/, 'Reading your material'], [/^inventory|^curriculum_scope/, 'Setting the lesson scope'], [/^objective_batch/, 'Planning learning objectives'],
  [/^assessment_verify|^assessment_valid|^reference/, 'Checking the assessments'], [/^assessment/, 'Writing assessments'], [/^author_recap|^verify_recap/, 'Writing the recap'],
  [/^author/, 'Writing the explanation'], [/^verify/, 'Checking the explanation'], [/^speech/, 'Recording narration'], [/^render/, 'Preparing scenes'], [/^short_grade/, 'Grading your answer']]
export const stageLabel = stage => STAGES.find(([pattern]) => pattern.test(stage || ''))?.[1] || (stage || 'queued').replaceAll('_', ' ')
export const isFinished = state => ['complete', 'complete_with_support'].includes(state)
export function SessionProgress({ session }) {
  const total = session.total_objectives || 0, covered = Math.min(total, session.covered_objectives || 0)
  return total > 0 ? <div className="session-progress"><progress aria-label={`Progress for ${session.title}`} max={total} value={covered} /><p className="muted">{covered} of {total} objectives covered · {session.passed_objectives || 0} passed independently</p></div> : null
}
function timeRange(seconds) { return seconds < 60 ? `${Math.max(5, Math.ceil(seconds / 5) * 5)} sec` : `${Math.ceil(seconds / 60)} min` }
export function JobEta({ eta, compact = false }) {
  if (!eta || ['completed', 'cancelled', 'failed'].includes(eta.status)) return null
  if (eta.status === 'taking_longer') return <p className="job-eta">Taking longer than estimated. Work is still running; the completion time is uncertain.</p>
  if (eta.status === 'recovering') return <p className="job-eta">Waiting for a worker to recover this job. ETA unavailable.</p>
  if (eta.status === 'timing_unavailable') return <p className="job-eta">Generation is running. ETA will be available for newly started jobs.</p>
  if (!['queued', 'running'].includes(eta.status)) return <p className="job-eta">Waiting for your attention. The estimate resumes when preparation restarts.</p>
  if (eta.upper_seconds == null) return null
  const lower = eta.lower_seconds || 0, upper = eta.upper_seconds
  return <div className={`job-eta ${compact ? 'compact' : ''}`}><strong>Estimated {eta.status === 'queued' ? 'generation time' : 'time remaining'}: {lower > 0 ? `${timeRange(lower)}–${timeRange(upper)}` : `up to ${timeRange(upper)}`}</strong>
    <p>{eta.status === 'queued' ? 'Once a worker starts; queue wait is additional. ' : ''}{eta.basis === 'recent_completed_runs' ? `Based on ${eta.sample_count} comparable completed runs.` : 'Rough initial range; model speed and lesson size can change it.'}{!compact && ` Target: ${eta.target}.`}</p>
  </div>
}
export function JobCard({ job }) {
  return <article className="panel preparation-card"><div className="row"><Badge>{job.state}</Badge><span className="muted">{job.kind.replaceAll('_', ' ')}</span></div><h3>{job.title || 'Preparing your material'}</h3><p>{stageLabel(job.stage)}</p><JobEta eta={job.eta} compact /><Link className="button secondary" to={`/jobs/${job.id}`}>{['failed', 'waiting_for_input', 'waiting_for_review', 'cancelled'].includes(job.state) ? 'Resolve preparation' : 'View preparation'}</Link></article>
}
export function JobView({ id }) {
  const { data: job, error, reload } = useResource(`/api/jobs/${id}`, 3500), [actionError, setActionError] = useState('')
  async function action(name) { try { await post(`/api/jobs/${id}/${name}`); reload() } catch (e) { setActionError(e.message) } }
  if (!job) return <Notice error={!!error}>{error || 'Loading preparation…'}</Notice>
  return <article className="panel job"><Link to={job.course_id ? `/classroom/${job.course_id}` : '/'}>← Back to {job.course_id ? 'classroom' : 'independent study'}</Link><div className="row spaced"><h2>{job.title || 'Preparation'}</h2><Badge>{job.state}</Badge></div><p>{['queued', 'running'].includes(job.state) ? stageLabel(job.stage) + '…' : stageLabel(job.stage)}</p>{['queued', 'running'].includes(job.state) && <div className="generation-activity" aria-label="Preparation in progress" />}<JobEta eta={job.eta} /><p className="muted">Stages are saved. You can leave this page and return.</p>
    <Notice error={!!job.error_code}>{job.result?.message || job.error_code}</Notice><Notice error>{actionError}</Notice>
    {['queued', 'running'].includes(job.state) && <button className="secondary" onClick={() => action('cancel')}>Cancel preparation</button>}
    {job.kind !== 'grade' && ['failed', 'cancelled', 'waiting_for_input', 'waiting_for_review'].includes(job.state) && <button onClick={() => action('retry')}>Retry saved stages</button>}
    {job.kind === 'grade' && ['failed', 'cancelled', 'waiting_for_input'].includes(job.state) && <p>Return to the saved learning checkpoint to retry grading.</p>}
    {job.result?.skipped_sections?.length > 0 && <details><summary>{job.result.skipped_sections.length} unreadable section(s) were skipped</summary><ul>{job.result.skipped_sections.map(x => <li key={x}>{x}</li>)}</ul></details>}
    {job.result?.curriculum_id && <Link className="button" to={`/lessons/${job.result.curriculum_id}`}>{job.kind === 'quick_lesson' ? 'Open your lesson ↗' : 'Open curriculum'}</Link>}
    {job.result?.source_id && <Link className="button" to={`/sources/${job.result.source_id}`}>Inspect source preview</Link>}
  </article>
}
