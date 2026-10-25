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
export function JobView({ id }) {
  const { data: job, error, reload } = useResource(`/api/jobs/${id}`, 3500), [actionError, setActionError] = useState('')
  async function action(name) { try { await post(`/api/jobs/${id}/${name}`); reload() } catch (e) { setActionError(e.message) } }
  if (!job) return <Notice error={!!error}>{error || 'Loading preparation…'}</Notice>
  return <article className="panel job"><div className="row"><h2>Preparation</h2><Badge>{job.state}</Badge></div><p>{job.stage.replaceAll('_', ' ')}</p><p className="muted">Stages are saved. You can leave this page and return.</p>
    <Notice error={!!job.error_code}>{job.result?.message || job.error_code}</Notice><Notice error>{actionError}</Notice>
    {['queued', 'running'].includes(job.state) && <button className="secondary" onClick={() => action('cancel')}>Cancel preparation</button>}
    {job.kind !== 'grade' && ['failed', 'cancelled', 'waiting_for_input', 'waiting_for_review'].includes(job.state) && <button onClick={() => action('retry')}>Retry saved stages</button>}
    {job.kind === 'grade' && ['failed', 'cancelled', 'waiting_for_input'].includes(job.state) && <p>Return to the saved learning checkpoint to retry grading.</p>}
    {job.result?.curriculum_id && <Link className="button" to={`/lessons/${job.result.curriculum_id}`}>Open curriculum</Link>}
    {job.result?.source_id && <Link className="button" to={`/sources/${job.result.source_id}`}>Inspect source preview</Link>}
  </article>
}
