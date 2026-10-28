import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, post } from './api'
import { Notice } from './common'

export function ConfirmAction({ label, title, children, confirmLabel = label, onConfirm, onDone, className = 'danger-text', ariaLabel }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const dialog = useRef(null), trigger = useRef(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    if (dialog.current.showModal) dialog.current.showModal()
    else dialog.current.setAttribute('open', '')
    return () => { const menu = previous?.closest?.('details'); const target = menu && !menu.open ? menu.querySelector('summary') : previous; if (target?.isConnected) target.focus() }
  }, [open])
  async function confirm() {
    setBusy(true); setError('')
    try { await onConfirm(); setOpen(false); onDone?.() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  function close() { if (!busy) { setOpen(false); setError('') } }
  return <><button ref={trigger} type="button" className={className} aria-label={ariaLabel} onClick={() => { setError(''); setOpen(true) }}>{label}</button>{open && createPortal(
    <dialog ref={dialog} className="confirm-dialog" aria-label={title} onCancel={e => { e.preventDefault(); close() }} onClick={e => { if (e.target === dialog.current) close() }}>
      <h2>{title}</h2><div className="confirm-copy">{children}</div><Notice error>{error}</Notice>
      <div className="dialog-actions"><button className="secondary" disabled={busy} autoFocus onClick={close}>Cancel</button><button className="danger-button" disabled={busy} onClick={confirm}>{busy ? 'Please wait…' : confirmLabel}</button></div>
    </dialog>, document.body)}</>
}

export function OptionsMenu({ title, children }) {
  const ref = useRef(null)
  useEffect(() => {
    function outside(event) { if (ref.current && !ref.current.contains(event.target)) ref.current.open = false }
    function escape(event) { if (event.key === 'Escape' && ref.current?.open) { ref.current.open = false; ref.current.querySelector('summary')?.focus() } }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])
  return <details ref={ref} className="options-menu"><summary aria-label={`Options for ${title}`} title="Options"><span aria-hidden="true">•••</span></summary><div className="options-menu-content">{children}</div></details>
}

export function LessonOptions({ lesson, onDeleted }) {
  return <OptionsMenu title={lesson.title}><ConfirmAction label="Delete lesson" ariaLabel={`Delete lesson ${lesson.title}`} title={`Delete “${lesson.title}”?`} onConfirm={() => api(`/api/lessons/${lesson.lesson_id || lesson.id}`, { method: 'DELETE' })} onDone={onDeleted}>
    <p>This lesson and its learning sessions will leave your workspace. Active preparation will be cancelled.</p><p>Saved sources remain in your source library. Lesson records are archived, and classroom assessment history is retained.</p>
  </ConfirmAction></OptionsMenu>
}

export function LeaveClassroom({ course, onLeft, className }) {
  return <ConfirmAction label="Leave classroom" ariaLabel={`Leave classroom ${course.title}`} className={className || 'danger-text'} title={`Leave “${course.title}”?`} onConfirm={() => post(`/api/courses/${course.id}/leave`)} onDone={onLeft}>
    <p>You’ll lose access to this classroom’s assignments. Your recorded classroom work stays in the teacher’s history.</p><p>You can rejoin with the class code while enrollment is open.</p>
  </ConfirmAction>
}
