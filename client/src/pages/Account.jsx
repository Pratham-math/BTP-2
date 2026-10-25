import { useState } from 'react'
import { useAuth } from '../platform/auth'
import { post } from '../platform/api'
import { Badge, Notice, PageHead, useResource } from '../platform/common'

export function Account() {
  const auth = useAuth(), [confirmation, setConfirmation] = useState(''), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [receipt, setReceipt] = useState(null)
  const erasures = useResource(auth.profile.privilege === 'administrator' ? '/api/admin/erasures' : null, 10000)
  async function erase(event) {
    event.preventDefault(); setError(''); setBusy(true)
    try { setReceipt(await post('/api/me/erasure', { confirmation })) }
    catch (error) { setError(error.message) }
    finally { setBusy(false) }
  }
  async function retry(id) {
    try { await post(`/api/admin/erasures/${id}/retry`); erasures.reload() }
    catch (error) { setError(error.message) }
  }
  return <><PageHead eyebrow="YOUR ACCOUNT" title="Account and privacy">Your independent study is private. Classroom reports are limited to the relevant course.</PageHead>
    <section className="panel narrow"><h2>{auth.profile.display_name}</h2><p>{auth.profile.email}</p><Badge>{auth.profile.privilege}</Badge></section>
    <section className="panel narrow"><h2>Request account deletion</h2>{receipt ? <>
      <Notice>{receipt.message}</Notice><p>Request reference: {receipt.job_id}</p><p>This receipt does not confirm that all copies are already erased. An operator tracks cleanup and authentication deletion separately.</p>
      <button onClick={auth.signOut}>Finish and sign out</button>
    </> : <form className="form" onSubmit={erase}>
      <p>This disables access immediately and queues deletion of private study data. Your name and email are removed from application records. Classroom grades and completion records are anonymized and retained; shared classroom teaching material is preserved.</p>
      <p>Cleanup needs the maintenance worker and storage access. Authentication identity deletion also needs operator configuration. Backup copies expire under the institution’s retention policy; no expiry period has been agreed yet. This action cannot be undone in the app.</p>
      <label>Type DELETE to confirm<input value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="off" required pattern="DELETE" /></label>
      <button disabled={busy || confirmation !== 'DELETE'}>{busy ? 'Requesting deletion…' : 'Disable account and request deletion'}</button>
    </form>}<Notice error>{error}</Notice></section>
    {auth.profile.privilege === 'administrator' && <section className="panel"><h2>Account cleanup requests</h2><Notice error>{erasures.error}</Notice>
      {erasures.data?.length === 0 && <p>No account cleanup requests.</p>}{erasures.data?.map(job => <div className="list-row" key={job.id}><div><strong>{job.account_id}</strong><p>{job.result?.message || job.error_code || job.stage}</p></div><Badge>{job.state}</Badge>{['failed', 'waiting_for_input'].includes(job.state) && <button className="secondary" onClick={() => retry(job.id)}>Retry cleanup</button>}</div>)}
    </section>}
  </>
}
