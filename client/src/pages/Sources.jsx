import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, media, post } from '../platform/api'
import { Badge, Empty, JobView, Notice, PageHead, useResource } from '../platform/common'
import { useAuth } from '../platform/auth'

const types = { text: 'Notes', topic: 'Topic', youtube: 'YouTube', pdf: 'PDF', pptx: 'Slides', ppt: 'Slides', image: 'Image' }
const warningText = flag => ({ author_confirmation_required: 'Check this extraction against the original.', ocr_required: 'This section needs a readable transcription.', figure_confirmation_required: 'Verify the figure labels and relationships.', empty_slide: 'Check this slide for missing content.' }[flag] || flag.replaceAll('_', ' '))
function status(source) {
  if (source.state === 'confirmed') return 'ready'
  if (source.state === 'needs_confirmation') return 'review'
  if (['failed', 'cancelled', 'waiting_for_input', 'waiting_for_review'].includes(source.job_state)) return 'attention'
  return 'processing'
}
const statusText = { ready: 'Ready for lessons', review: 'Needs review', attention: 'Needs attention', processing: 'Extracting' }
const lessonLink = ids => `/lessons/new?${new URLSearchParams(ids.map(id => ['source', id]))}`

function SourceSteps({ step }) {
  return <ol className="source-steps" aria-label="Source workflow">{['Add material', 'Review & correct', 'Create a lesson'].map((label, index) => <li key={label} aria-current={step === index ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}</ol>
}

function RemoveSource({ id, title, onRemoved }) {
  const [confirming, setConfirming] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  async function remove() {
    setBusy(true); setError('')
    try { await api(`/api/sources/${id}`, { method: 'DELETE' }); onRemoved() }
    catch (e) { setError(e.message); setBusy(false) }
  }
  return <div className="source-remove">
    {confirming ? <><p>Remove “{title}” and its saved extraction? Sources used by lessons must be retained until those lessons are retired.</p><div className="row"><button disabled={busy} onClick={remove}>{busy ? 'Removing…' : 'Confirm removal'}</button><button className="secondary" disabled={busy} onClick={() => { setConfirming(false); setError('') }}>Keep source</button></div></> : <button className="secondary" aria-label={`Remove source ${title}`} onClick={() => setConfirming(true)}>Remove</button>}
    <Notice error>{error}</Notice>
  </div>
}

export function SourcesPage() {
  const { config } = useAuth(), features = config?.source_features || { text: true }
  const sources = useResource('/api/sources', 5000), navigate = useNavigate()
  const [kind, setKind] = useState('text'), [title, setTitle] = useState(''), [text, setText] = useState(''), [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [query, setQuery] = useState(''), [filter, setFilter] = useState('all'), [selected, setSelected] = useState([])
  const fileInput = useRef(null)
  const items = sources.data || [], ready = items.filter(x => status(x) === 'ready'), chosen = ready.filter(x => selected.includes(x.id))
  const visible = items.filter(x => (filter === 'all' || status(x) === filter) && `${x.title} ${types[x.kind] || x.kind}`.toLowerCase().includes(query.toLowerCase().trim()))
  const uploadReady = features.document || features.image
  const available = kind === 'upload' ? uploadReady : kind === 'text' || features[kind]
  function chooseFile(value) {
    setMessage(''); setFile(null)
    if (!value) return
    if (!value.size || value.size > 25 * 1024 * 1024) { setMessage('Choose a nonempty file of up to 25 MB. Split larger sources into batches.'); return }
    setFile(value)
  }
  async function create(event) {
    event.preventDefault(); setBusy(true); setMessage('')
    try {
      let source
      if (kind === 'upload') {
        const body = new FormData(); body.append('file', file)
        source = await api('/api/sources/upload', { method: 'POST', body })
      } else source = await post('/api/sources', { title, kind, text })
      navigate(`/sources/${source.id}`)
    } catch (e) { setMessage(e.message) } finally { setBusy(false) }
  }
  return <>
    <PageHead eyebrow="SOURCE LIBRARY" title="Your material. A clear path forward.">Add notes, documents or a video. Check the extracted material once, then reuse it in your lessons.</PageHead>
    <SourceSteps step={0} />
    <div className="source-workspace">
      <section className="panel source-add"><h2>Add a source</h2><p className="muted">Choose what you have. You’ll review the preview before using it.</p>
        <form className="form" onSubmit={create}>
          <label>Source type<select value={kind} disabled={busy} onChange={e => { setKind(e.target.value); setMessage('') }}><option value="text">Typed or pasted notes</option><option value="upload">Document or image</option>{features.topic && <option value="topic">Topic · reference collection</option>}<option value="youtube">Public YouTube video</option></select></label>
          {kind === 'upload' ? <>
            <div className="source-file-picker"><p>PDFs, slides and images</p><p className="muted">One file at a time · up to 25 MB</p><label className="file-button">Choose source file<input ref={fileInput} type="file" aria-label="Source file" disabled={busy || !uploadReady} accept={[features.document && '.pdf,.pptx,.ppt', features.image && '.png,.jpg,.jpeg'].filter(Boolean).join(',')} onChange={e => chooseFile(e.target.files?.[0])} /></label></div>
            {file && <div className="source-file-selection"><div><strong>{file.name}</strong><p className="muted">{(file.size / 1024).toFixed(1)} KB · ready to upload</p></div><button type="button" className="secondary" disabled={busy} onClick={() => { setFile(null); if (fileInput.current) fileInput.current.value = '' }}>Remove file</button></div>}
          </> : <>
            <label>Title<input required minLength={3} maxLength={160} disabled={busy} placeholder={kind === 'youtube' ? 'e.g. Binary search lecture' : 'e.g. Week 3 · loops and lists'} value={title} onChange={e => setTitle(e.target.value)} /></label>
            <label>{kind === 'youtube' ? 'Public video URL' : kind === 'topic' ? 'What do you want to study?' : 'Source text'}{kind === 'youtube' ? <input type="url" required disabled={busy} placeholder="https://www.youtube.com/watch?v=…" value={text} onChange={e => setText(e.target.value)} /> : <textarea required minLength={3} maxLength={250000} disabled={busy} rows={9} value={text} onChange={e => setText(e.target.value)} spellCheck={false} placeholder={kind === 'topic' ? 'Describe the topic and what you need to understand.' : 'Paste your notes here. Keep code indentation and equations intact.'} />}</label>
          </>}
          {kind === 'youtube' && <p className="muted">Public videos up to one hour. You’ll review timestamped derived notes against the video. Extraction uses Gemini.</p>}
          {!available && <Notice error>{kind === 'youtube' ? 'YouTube extraction needs a server-side Gemini key and a configured Gemini extraction model. You can paste a transcript as text notes instead.' : 'This adapter is not configured yet. Paste readable notes to continue.'}</Notice>}
          <Notice error>{message}</Notice><button disabled={busy || !available || (kind === 'upload' && !file)}>{busy ? (kind === 'upload' ? 'Uploading material…' : 'Adding source…') : 'Create source preview'}</button>
          <p className="muted">Your sources are private to your account. Classroom lessons share only their selected teaching material.</p>
        </form>
      </section>
      <section className="source-library" aria-label="Saved sources"><div className="section-head"><h2>Saved sources</h2><span className="muted">{items.length} total · {ready.length} ready</span></div>
        <div className="source-library-tools"><label>Search sources<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search title or type" /></label><label>Status<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All sources</option>{Object.entries(statusText).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
        <Notice error>{sources.error}</Notice>
        {chosen.length > 0 && <div className="source-selection-bar"><strong>{chosen.length} source{chosen.length === 1 ? '' : 's'} selected</strong><Link className="button" to={lessonLink(chosen.map(x => x.id))}>Create lesson from selection</Link><button className="secondary" onClick={() => setSelected([])}>Clear selection</button></div>}
        {!sources.data && !sources.error && <p role="status">Loading your sources…</p>}
        <div className="source-cards">{visible.map(source => <article className="panel source-card" key={source.id}>
          <div className="source-card-heading"><span className="source-type">{types[source.kind] || source.kind}</span><span className={`source-state ${status(source)}`}>{statusText[status(source)]}</span></div>
          <h3><Link to={`/sources/${source.id}`}>{source.title}</Link></h3>
          <p className="muted">{source.block_count !== undefined && `${source.block_count} section${source.block_count === 1 ? '' : 's'}`}{source.unresolved_blocks > 0 && ` · ${source.unresolved_blocks} to check`}{source.created_at && ` · ${new Date(source.created_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`}</p>
          <div className="source-card-actions"><Link className="button secondary" to={`/sources/${source.id}`}>{status(source) === 'ready' ? 'Open source' : status(source) === 'processing' ? 'View extraction' : status(source) === 'attention' ? 'Resolve extraction' : 'Review source'}</Link>{status(source) === 'ready' && <label className="check-label"><input type="checkbox" aria-label={`Select ${source.title} for a lesson`} checked={selected.includes(source.id)} disabled={!selected.includes(source.id) && chosen.length >= 20} onChange={e => setSelected(e.target.checked ? [...selected, source.id] : selected.filter(id => id !== source.id))} />Use in lesson</label>}</div>
          <RemoveSource id={source.id} title={source.title} onRemoved={sources.reload} />
        </article>)}</div>
        {sources.data && !items.length && <Empty title="No sources yet">Add your first material on the left. We’ll guide you through reviewing it.</Empty>}
        {items.length > 0 && !visible.length && <Empty title="No matching sources">Try another search or status filter.</Empty>}
      </section>
    </div>
  </>
}

function SourceImage({ sourceId, block }) {
  const [visible, setVisible] = useState(false)
  const preview = useResource(visible ? `/api/sources/${sourceId}/evidence/${block.id}/image` : null, 240000), [src, setSrc] = useState(null)
  useEffect(() => { let on = true; media(preview.data?.url).then(x => on && setSrc(x)).catch(() => {}); return () => { on = false } }, [preview.data?.url])
  if (!block.image_key) return null
  return <aside className="source-image"><button className="secondary" onClick={() => setVisible(value => !value)}>{visible ? 'Hide page image' : 'Compare original page image'}</button>
    {visible && <><Notice error>{preview.error}</Notice>{src ? <img src={src} alt={`Source reference for ${block.location}. Check its text, notation and diagrams against the extracted evidence.`} loading="lazy" referrerPolicy="no-referrer" /> : !preview.error && <p>Opening a private page preview…</p>}<p className="muted">Use the original to check text, symbols and diagrams.</p></>}
  </aside>
}

export function SourceDetail() {
  const { id } = useParams(), navigate = useNavigate(), source = useResource(`/api/sources/${id}`, 5000)
  const [snapshot, setSnapshot] = useState(null), [evidence, setEvidence] = useState(null), [message, setMessage] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false), [changed, setChanged] = useState(false)
  const [renaming, setRenaming] = useState(false), [title, setTitle] = useState('')
  const loadedVersion = useRef(null), dirty = useRef(false)
  useEffect(() => { loadedVersion.current = null; dirty.current = false; setEvidence(null); setSnapshot(null); setChanged(false); setRenaming(false); setMessage(''); setError('') }, [id])
  useEffect(() => {
    if (!source.data || source.data.id !== id) return
    if (loadedVersion.current !== null && source.data.version < loadedVersion.current) return
    setSnapshot(current => current?.version > source.data.version ? current : source.data)
    if (!dirty.current && loadedVersion.current !== source.data.version) { setEvidence(source.data.evidence); loadedVersion.current = source.data.version }
  }, [source.data, id])
  function editEvidence(value) { dirty.current = true; setChanged(true); setEvidence(value); setMessage('') }
  async function save(confirm) {
    setBusy(true); setError(''); setMessage('')
    try {
      const value = await api(`/api/sources/${id}/preview`, { method: 'PUT', body: JSON.stringify({ expected_version: loadedVersion.current, evidence, confirm, note: 'Author checked the source and saved this extraction revision.' }) })
      dirty.current = false; setChanged(false); loadedVersion.current = value.version; setSnapshot(value); setEvidence(value.evidence)
      setMessage(confirm ? 'Source confirmed. Choose Use in a lesson to continue.' : 'Corrections saved. Review the remaining sections, then confirm this source.')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function rename(event) {
    event.preventDefault(); setBusy(true); setError('')
    try { const value = await api(`/api/sources/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }); setSnapshot(value); setRenaming(false) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function original() { try { const { url } = await api(`/api/sources/${id}/original`); window.open(url, '_blank', 'noopener,noreferrer') } catch (e) { setError(e.message) } }
  const data = snapshot?.id === id ? snapshot : null
  if (!data) return <Notice error={!!source.error}>{source.error || 'Loading source…'}</Notice>
  const blocks = evidence || [], unresolved = blocks.filter(x => x.uncertainty.length).length, confirmed = data.confirmed && !changed
  return <>
    <Link className="source-back" to="/sources">← Source library</Link>
    <PageHead eyebrow="SOURCE PREVIEW" title={data.title} action={<Badge>{confirmed ? 'Ready for lessons' : 'Review source'}</Badge>}>Check the extraction against your original. Your corrections create a new version without changing existing lessons.</PageHead>
    <SourceSteps step={confirmed ? 2 : 1} /><Notice>{message}</Notice><Notice error>{error || source.error}</Notice>
    {changed && loadedVersion.current !== data.version && <Notice error>A newer source version is available. Your unsaved edits are still here. <button className="secondary" onClick={() => { dirty.current = false; setChanged(false); loadedVersion.current = data.version; setEvidence(data.evidence); setError('') }}>Discard edits and load latest version</button></Notice>}
    <div className="source-review-layout"><div>
      {!blocks.length && <><div className="panel"><h2>Preparing your source</h2><p>Extraction may take a few minutes. You can leave and return; this page updates automatically. Review the material when it arrives.</p></div>{data.job_id && <JobView id={data.job_id} />}</>}
      {blocks.map((block, index) => <section className="panel source-block" key={block.id}>
        <div className="source-card-heading"><h2>{block.location}</h2><Badge>{block.uncertainty.length ? 'Check against original' : 'Ready to confirm'}</Badge></div>
        <p className="muted">Section {index + 1} of {blocks.length} · {block.method.replaceAll('-', ' ')}</p>
        <label className="sr-only" htmlFor={`evidence-${index}`}>Extracted text for {block.location}</label><textarea id={`evidence-${index}`} maxLength={20000} disabled={busy} rows={Math.min(18, Math.max(6, block.text.split('\n').length))} value={block.text} spellCheck={false} onChange={e => editEvidence(blocks.map((x, i) => i === index ? { ...x, text: e.target.value } : x))} />
        <SourceImage sourceId={id} block={block} />
        {block.uncertainty.length > 0 && <div className="source-check"><ul>{block.uncertainty.map(flag => <li key={flag}>{warningText(flag)}</li>)}</ul><label className="check-label"><input type="checkbox" disabled={busy} checked={false} onChange={() => editEvidence(blocks.map((x, i) => i === index ? { ...x, uncertainty: [] } : x))} />I corrected this block using the original and verified its uncertain symbols.</label></div>}
      </section>)}
    </div><aside className="source-review-sidebar"><section className="panel"><h2>{confirmed ? 'Ready to teach from' : 'Your review'}</h2>
      <p className="muted">{types[data.kind] || data.kind} · version {data.version || 'being prepared'}</p>
      {blocks.length > 0 && <><p><strong>{blocks.length - unresolved} of {blocks.length}</strong> sections clear of extraction warnings</p><progress aria-label="Sections clear of extraction warnings" max={blocks.length} value={blocks.length - unresolved} /><p className="muted">Check completeness, code indentation, numbers, units and diagrams before confirming.</p></>}
      {data.has_original && <button className="secondary" onClick={original}>Open uploaded original</button>}{data.original_url && <a className="button secondary" href={data.original_url} target="_blank" rel="noopener noreferrer">Open YouTube video</a>}
      {data.kind === 'youtube' && <p className="muted">These are derived video notes, not an exact transcript. Compare their timestamps with the video.</p>}
      {data.warnings?.length > 0 && <details><summary>Extraction notes ({data.warnings.length})</summary><ul>{data.warnings.map((warning, index) => <li key={index}>{warning.location}: {warningText(warning.code)}</li>)}</ul></details>}
      <p role="status" className="muted">{changed ? 'Unsaved changes' : 'Latest saved version'}</p>
      {blocks.length > 0 && <div className="source-review-buttons"><button className="secondary" disabled={busy || !changed} onClick={() => save(false)}>Save corrections</button>{!confirmed && <button disabled={busy || unresolved > 0 || blocks.some(x => !x.text.trim())} onClick={() => save(true)}>{busy ? 'Saving…' : 'Confirm source for lessons'}</button>}</div>}
      {unresolved > 0 && <p className="muted">Check {unresolved} flagged section{unresolved === 1 ? '' : 's'} to enable confirmation.</p>}
      {confirmed && <Link className="button" to={lessonLink([id])}>Use in a lesson →</Link>}
    </section><section className="panel"><h2>Manage source</h2>
      {renaming ? <form className="form" onSubmit={rename}><label>Source title<input required minLength={3} maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label><button disabled={busy}>Save title</button><button type="button" className="secondary" disabled={busy} onClick={() => setRenaming(false)}>Cancel rename</button></form> : <button className="secondary" onClick={() => { setTitle(data.title); setRenaming(true) }}>Rename source</button>}
      <RemoveSource id={id} title={data.title} onRemoved={() => navigate('/sources')} />
    </section></aside></div>
  </>
}
