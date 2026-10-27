import { lazy, Suspense, useState } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from './platform/auth'
import { Badge, JobView, Notice } from './platform/common'
import { Library, LessonDetail, NewLesson, ProgressPage, SourcesPage, SourceDetail } from './pages/Independent'
import { Classroom, CoursePage, ReviewPage } from './pages/Classroom'
import { Account } from './pages/Account'
const Player = lazy(() => import('./player/Player').then(module => ({ default: module.Player })))
function JobPage() { const { id } = useParams(); return <JobView id={id} /> }
function LocalLogin({ auth }) {
  const [mode, setMode] = useState('login'), [form, setForm] = useState({ name: '', login: '', password: '' }), [busy, setBusy] = useState(false)
  const field = key => e => setForm({ ...form, [key]: e.target.value })
  async function submit(e) {
    e.preventDefault(); setBusy(true)
    await auth.localAuth(mode, mode === 'register' ? form : { login: form.login, password: form.password }); setBusy(false)
  }
  return <form className="local-login" onSubmit={submit}>
    {mode === 'register' && <label>Your name<input required maxLength={120} value={form.name} onChange={field('name')} autoComplete="name" /></label>}
    <label>Email or username<input required minLength={3} maxLength={320} value={form.login} onChange={field('login')} autoComplete="username" /></label>
    <label>Password<input required type="password" minLength={8} maxLength={200} value={form.password} onChange={field('password')} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} /></label>
    <div className="row"><button className="primary" disabled={busy}>{mode === 'register' ? 'Create account' : 'Sign in'}</button>
      <button type="button" className="text-button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? 'New here? Create an account' : 'Have an account? Sign in'}</button></div>
  </form>
}
function Shell() {
  const auth = useAuth()
  if (auth.loading) return <div className="loading-screen" role="status">Opening your workspace…</div>
  if (auth.session && !auth.profile) return <main className="loading-screen"><section className="panel narrow">
    <h1>Your workspace could not load</h1><p>You’re still signed in. Try loading your account again.</p>
    <Notice error>{auth.error}</Notice><div className="row"><button onClick={auth.retryProfile}>Try again</button><button className="secondary" onClick={auth.signOut}>Sign out</button></div>
  </section></main>
  if (!auth.session) return <main className="login-screen">
    <Link className="brand" to="/"><span className="brand-icon">b.</span>BTP2<span className="brand-sub">LEARNING STUDIO</span></Link>
    <section className="login-content"><p className="eyebrow">Understand. Practice. Build.</p><h1>Make the next<br />concept click.</h1>
      <p>Source-grounded lessons, visual explanations, and practice that helps you decide what to learn next.</p>
      {auth.config?.auth_mode === 'local' ? <LocalLogin auth={auth} /> : auth.config?.auth_configured && auth.config?.google_oauth_verified ? <button className="primary" onClick={auth.signIn}>Continue with Google <span aria-hidden="true">↗</span></button>
        : <Notice>Google sign-in setup and verification are still required. See PLATFORM_SETUP.md before opening enrollment.</Notice>}
      <Notice error>{auth.error}</Notice>
      {auth.config?.setup_required?.length > 0 && <div className="setup-note"><h2>Setup in progress</h2><p>{auth.config.setup_required.map(x => x.replaceAll('_', ' ')).join(' · ')}</p></div>}
    </section><aside className="login-visual" aria-hidden="true"><div className="diagram-orbit orbit-one" /><div className="diagram-orbit orbit-two" /><div className="concept-node node-one">01 <strong>Explore</strong></div><div className="concept-node node-two">02 <strong>Understand</strong></div><div className="concept-node node-three">03 <strong>Apply</strong></div><p>One concept.<br />A clearer connection.</p></aside>
  </main>
  return <div className="app-shell"><aside className="sidebar"><Link className="brand" to="/"><span className="brand-icon">b.</span>BTP2</Link>
    <p className="nav-label">YOUR WORKSPACE</p><nav aria-label="Main navigation"><NavLink to="/" end><span aria-hidden="true">◫</span>Independent study</NavLink><NavLink to="/classroom"><span aria-hidden="true">▦</span>Classroom</NavLink><NavLink to="/sources"><span aria-hidden="true">▤</span>Source library</NavLink><NavLink to="/progress"><span aria-hidden="true">↗</span>Your progress</NavLink><NavLink to="/account"><span aria-hidden="true">○</span>Account</NavLink></nav>
    <div className="sidebar-note"><span className="status-dot" />Learn with evidence<p>Private study stays private. Classroom content carries teacher review.</p></div>
    <div className="account"><div className="avatar">{auth.profile.display_name[0]}</div><div><strong>{auth.profile.display_name}</strong><small>{auth.profile.privilege}</small></div><button className="text-button" onClick={auth.signOut}>Sign out</button></div>
  </aside><div className="main-shell"><header className="workspace-bar"><span>Learning studio <span className="muted">/ Your workspace</span></span><Badge>English · Python</Badge></header>
    <main className="page"><Notice error>{auth.error}</Notice><Routes><Route path="/" element={<Library />} /><Route path="/lessons/new" element={<NewLesson />} /><Route path="/lessons/:id" element={<LessonDetail />} />
      <Route path="/sources" element={<SourcesPage />} /><Route path="/sources/:id" element={<SourceDetail />} /><Route path="/account" element={<Account />} /><Route path="/classroom" element={<Classroom />} /><Route path="/classroom/:id" element={<CoursePage />} />
      <Route path="/reviews/:id" element={<ReviewPage />} /><Route path="/learn/:id" element={<Suspense fallback={<Notice>Opening the lesson player…</Notice>}><Player /></Suspense>} /><Route path="/jobs/:id" element={<JobPage />} /><Route path="/progress" element={<ProgressPage />} />
      <Route path="/auth/callback" element={<Navigate replace to="/" />} /><Route path="*" element={<Navigate replace to="/" />} /></Routes></main>
  </div></div>
}
export default function App() { return <BrowserRouter><AuthProvider><Shell /></AuthProvider></BrowserRouter> }
