import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Empty, isFinished, JobCard, Notice, PageHead, SessionProgress, useResource } from '../platform/common'
import { LessonOptions } from '../platform/actions'
import { useAuth } from '../platform/auth'

export function Library() {
  const { profile } = useAuth(), lessons = useResource('/api/lessons', 5000), sessions = useResource('/api/sessions', 5000), jobs = useResource('/api/jobs', 5000)
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('all')
  const owned = (lessons.data || []).filter(x => !x.course_id), privateSessions = (sessions.data || []).filter(x => !x.course_id)
  const active = privateSessions.filter(x => !isFinished(x.state)), completed = privateSessions.filter(x => isFinished(x.state))
  const preparation = (jobs.data || []).filter(x => !x.course_id && x.lesson_id && ['queued', 'running', 'failed', 'waiting_for_input', 'waiting_for_review'].includes(x.state))
  const visible = owned.filter(x => x.title.toLowerCase().includes(query.toLowerCase().trim()) && (filter === 'all' || (filter === 'ready' ? ['ready', 'playable_partial'].includes(x.availability) : !['ready', 'playable_partial'].includes(x.availability))))
  return <>
    <PageHead eyebrow="INDEPENDENT STUDY" title={`What will you understand next, ${profile.display_name.split(' ')[0]}?`} action={<Link className="button" to="/lessons/new">+ Create a lesson</Link>}>Your private workspace for turning source material into understanding. Pick up where you left off or start a new learning path.</PageHead>
    <div className="workspace-stats"><div><strong>{owned.length}</strong><span>Private lessons</span></div><div><strong>{active.length}</strong><span>In progress</span></div><div><strong>{completed.length}</strong><span>Completed sessions</span></div><div><strong>{preparation.filter(x => ['queued', 'running'].includes(x.state)).length}</strong><span>Being prepared</span></div></div>
    <Notice error>{lessons.error || sessions.error || jobs.error}</Notice>
    {active.length > 0 && <section><div className="section-head"><h2>Continue learning</h2><Link to="/progress">All your progress →</Link></div><div className="card-grid">{active.slice(0, 3).map(session => <article className="lesson-card" key={session.id}><Badge>{session.state}</Badge><h3>{session.title}</h3><SessionProgress session={session} /><Link className="button" to={`/learn/${session.id}`}>Resume lesson →</Link></article>)}</div></section>}
    {lessons.data && !owned.length && <section className="workspace-start"><div><p className="eyebrow">MAKE YOUR NEXT CONNECTION</p><h2>Start with curiosity.<br />Build with your material.</h2><p>Choose a topic, or combine sources you’ve already reviewed.</p></div><div className="workspace-start-actions"><Link className="workspace-action" to="/lessons/new"><strong>Explore a topic →</strong><span>Describe what you want to understand.</span></Link><Link className="workspace-action" to="/lessons/new?mode=sources"><strong>Learn from saved sources →</strong><span>Combine confirmed notes, slides or videos.</span></Link><Link className="workspace-action" to="/sources"><strong>Organize your material →</strong><span>Add, correct and review your sources.</span></Link></div></section>}
    {preparation.length > 0 && <section><div className="section-head"><h2>Lesson preparation</h2><span className="muted">Updates automatically</span></div><div className="card-grid">{preparation.slice(0, 6).map(job => <JobCard key={job.id} job={job} />)}</div></section>}
    <section><div className="section-head"><h2>Your lesson library</h2><span className="muted">{owned.length} lessons</span></div>
      <div className="workspace-filters"><label>Search lessons<input type="search" placeholder="Find a lesson" value={query} onChange={e => setQuery(e.target.value)} /></label><label>Lesson status<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All lessons</option><option value="ready">Ready to learn</option><option value="preparing">Planning & preparation</option></select></label></div>
      {!lessons.data && !lessons.error && <p role="status">Loading your lessons…</p>}
      <div className="card-grid">{visible.map(lesson => {
        const session = privateSessions.find(x => x.curriculum_id === lesson.curriculum_id), job = preparation.find(x => x.lesson_id === lesson.id)
        return <article className="lesson-card" key={lesson.id}><div className="card-heading"><Badge>{lesson.availability}</Badge><LessonOptions lesson={lesson} onDeleted={() => { lessons.reload(); sessions.reload(); jobs.reload() }} /></div><h3>{lesson.title}</h3><p className="muted">Private independent study</p>{session && <SessionProgress session={session} />}
          <div className="card-footer">{session && <Link className="button" to={`/learn/${session.id}`}>{isFinished(session.state) ? 'Revisit lesson' : 'Resume learning'}</Link>}{lesson.curriculum_id ? <Link className="card-link" to={`/lessons/${lesson.curriculum_id}`}>{session ? 'View learning path' : ['ready', 'playable_partial'].includes(lesson.availability) ? 'Open lesson →' : 'Review learning path →'}</Link> : job ? <Link className="button secondary" to={`/jobs/${job.id}`}>View preparation</Link> : <p className="muted">The curriculum is being prepared.</p>}</div>
        </article>
      })}</div>
      {lessons.data && !owned.length && <Empty title="Your first learning path starts here">Choose a topic above, or add material to your source library.</Empty>}
      {owned.length > 0 && !visible.length && <Empty title="No matching lessons">Try a different title or status filter.</Empty>}
    </section>
  </>
}
