import { AbsoluteFill, Audio, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// Validated scene JSON (server/visuals.py) + narration cues -> animated frame.
// Each cue starts one utterance; its visual_step says how far the visual has advanced.
const C = { paper: '#f7f4ec', ink: '#1f2a2e', soft: '#5f6b6d', line: '#d9d3c4', teal: '#0f766e', blue: '#2563eb', amber: '#b45309', red: '#b91c1c' }
const tone = name => C[name === 'ink' ? 'ink' : name] || C.teal
const ICON = { sun: '☀', plant: '🌱', water: '💧', cloud: '☁', computer: '💻', none: '' }

function useReveal(at) {
  const frame = useCurrentFrame(), { fps } = useVideoConfig()
  return spring({ frame: frame - at, fps, config: { damping: 18, stiffness: 120 } })
}
const Appear = ({ at, children, style }) => {
  const p = useReveal(at)
  return <div style={{ ...style, opacity: p, transform: `translateY(${(1 - p) * 18}px)` }}>{children}</div>
}

// Step-frame lookup: the frame at which each visual step became visible.
function stepFrames(cues, fps) {
  const first = {}
  for (const cue of cues) if (first[cue.step] === undefined) first[cue.step] = Math.round(cue.start * fps)
  return step => {
    let best = 0
    for (const [s, f] of Object.entries(first)) if (Number(s) <= step) best = Math.max(best, f)
    return first[step] ?? best
  }
}

function Box({ node, at }) {
  const p = useReveal(at)
  return <div style={{ opacity: p, transform: `scale(${.85 + .15 * p})`, border: `3px solid ${tone(node.color)}`, background: '#fff', borderRadius: 18,
    padding: '18px 22px', minWidth: 150, textAlign: 'center', fontSize: 30, fontWeight: 600, color: C.ink, boxShadow: '0 6px 0 rgba(31,42,46,.08)' }}>
    {ICON[node.icon] && <div style={{ fontSize: 40 }}>{ICON[node.icon]}</div>}{node.label}</div>
}

function Flow({ visual, step, at }) {
  // Nodes then their connecting edges, in list order (process / cycle).
  const total = visual.nodes.length, shown = Math.max(1, Math.ceil(((step + 1) / stepTotal(visual)) * total))
  const cycle = visual.kind === 'cycle'
  if (cycle) {
    const r = 210
    return <div style={{ position: 'relative', width: 760, height: 520 }}>
      <svg width="760" height="520" style={{ position: 'absolute' }}><circle cx="380" cy="260" r={r} fill="none" stroke={C.line} strokeWidth="4" strokeDasharray="10 12" /></svg>
      {visual.nodes.map((n, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / total
        return i < shown && <div key={n.id} style={{ position: 'absolute', left: 380 + r * Math.cos(a), top: 260 + r * Math.sin(a), transform: 'translate(-50%,-50%)' }}><Box node={n} at={at(stepFor(visual, i))} /></div> })}
    </div>
  }
  return <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', justifyContent: 'center' }}>
    {visual.nodes.map((n, i) => i < shown && <div key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
      {i > 0 && <Appear at={at(stepFor(visual, i))}><span style={{ fontSize: 44, color: C.soft }}>→</span></Appear>}<Box node={n} at={at(stepFor(visual, i))} /></div>)}
  </div>
}
const stepFor = (visual, i) => Math.floor(i * stepTotal(visual) / visual.nodes.length)

function Tree({ visual, step, at }) {
  const children = Object.fromEntries(visual.nodes.map(n => [n.id, []]))
  const parents = new Set(visual.edges.map(e => e.target))
  visual.edges.forEach(e => children[e.source].push(e.target))
  const root = visual.nodes.find(n => !parents.has(n.id))?.id, levels = []
  const walk = (id, d) => { (levels[d] ||= []).push(id); children[id].forEach(c => walk(c, d + 1)) }
  if (root) walk(root, 0)
  const order = levels.flat(), shown = Math.max(1, Math.ceil(((step + 1) / stepTotal(visual)) * order.length))
  const byId = Object.fromEntries(visual.nodes.map(n => [n.id, n]))
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 34, alignItems: 'center' }}>
    {levels.map((ids, d) => <div key={d} style={{ display: 'flex', gap: 28 }}>{ids.map(id => order.indexOf(id) < shown &&
      <Box key={id} node={byId[id]} at={at(Math.floor(order.indexOf(id) * stepTotal(visual) / order.length))} />)}</div>)}
  </div>
}

function Plot({ visual, step, at }) {
  const frame = useCurrentFrame()
  const W = 760, H = 440, pad = 60, xs = visual.points.map(p => p.x), ys = visual.points.map(p => p.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(0, ...ys), Math.max(...ys)]
  const sx = x => pad + (x - x0) / ((x1 - x0) || 1) * (W - 2 * pad), sy = y => H - pad - (y - y0) / ((y1 - y0) || 1) * (H - 2 * pad)
  const shown = Math.min(visual.points.length, Math.ceil(step / 2) + 1)
  let line = null
  if (visual.fit_line && step >= stepTotal(visual) - 1) {
    const n = xs.length, mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n
    const m = xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / (xs.reduce((a, x) => a + (x - mx) ** 2, 0) || 1)
    line = <line x1={sx(x0)} y1={sy(my + m * (x0 - mx))} x2={sx(x1)} y2={sy(my + m * (x1 - mx))} stroke={C.amber} strokeWidth="4" strokeDasharray="12 8" />
  }
  return <svg width={W} height={H} style={{ overflow: 'visible' }}>
    <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke={C.ink} strokeWidth="3" /><line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke={C.ink} strokeWidth="3" />
    <text x={W / 2} y={H - 12} textAnchor="middle" fontSize="24" fill={C.soft}>{visual.x_label}</text>
    <text x={18} y={H / 2} textAnchor="middle" fontSize="24" fill={C.soft} transform={`rotate(-90 18 ${H / 2})`}>{visual.y_label}</text>
    {visual.points.slice(0, shown).map((p, i) => { const a = at(Math.min(i * 2, stepTotal(visual) - 1)), r = interpolate(frame - a, [0, 12], [0, 11], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
      return <g key={i}><circle cx={sx(p.x)} cy={sy(p.y)} r={r} fill={C.teal} /><text x={sx(p.x)} y={sy(p.y) - 18} textAnchor="middle" fontSize="18" fill={C.soft} opacity={r / 11}>({p.x}, {p.y})</text></g> })}
    {line}
  </svg>
}

function Cells({ items, active, name, note }) {
  return <div>
    {name && <div style={{ fontSize: 24, color: C.soft, marginBottom: 8, fontFamily: 'monospace' }}>{name}</div>}
    <div style={{ display: 'flex', gap: 8 }}>{items.map((x, i) => <div key={i} style={{ textAlign: 'center' }}>
      <div style={{ width: 70, height: 70, display: 'grid', placeItems: 'center', fontSize: 28, fontFamily: 'monospace', borderRadius: 10,
        border: `3px solid ${i === active ? C.amber : C.line}`, background: i === active ? '#fff4e0' : '#fff', transition: 'all .2s' }}>{x}</div>
      <div style={{ fontSize: 18, color: C.soft, marginTop: 4 }}>{i}</div>
      {i === active && <div style={{ fontSize: 30, color: C.amber }}>▲</div>}</div>)}</div>
    {note && <div style={{ marginTop: 10, fontSize: 26, color: C.ink }}>{note}</div>}
  </div>
}

function CodeTrace({ visual, step }) {
  const state = step > 0 ? visual.trace[Math.min(step, visual.trace.length) - 1] : null
  return <div style={{ display: 'flex', gap: 40, alignItems: 'flex-start' }}>
    <pre style={{ margin: 0, background: '#1f2a2e', color: '#e8e4d8', padding: '22px 0', borderRadius: 14, fontSize: 25, lineHeight: 1.45, minWidth: 560 }}>
      {visual.code_lines.map((line, i) => <div key={i} style={{ padding: '0 24px', background: state?.line === i + 1 ? 'rgba(245,158,11,.28)' : 'transparent', borderLeft: `6px solid ${state?.line === i + 1 ? '#f59e0b' : 'transparent'}` }}>
        <span style={{ color: '#7c8a8c', marginRight: 18 }}>{String(i + 1).padStart(2)}</span>{line || ' '}</div>)}</pre>
    <div style={{ minWidth: 300 }}>
      <div style={{ fontSize: 22, letterSpacing: 2, color: C.soft, marginBottom: 10 }}>VARIABLES</div>
      {state ? Object.entries(state.variables).map(([k, v]) => <div key={k} style={{ fontFamily: 'monospace', fontSize: 28, padding: '6px 0', borderBottom: `2px solid ${C.line}` }}>
        <b style={{ color: C.teal }}>{k}</b> = {v}</div>) : <div style={{ fontSize: 24, color: C.soft }}>Not started</div>}
      {state?.array?.length > 0 && <div style={{ marginTop: 22 }}><Cells items={state.array} active={state.active_index} name={state.array_name} /></div>}
    </div>
  </div>
}

function Equation({ visual, step }) {
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 18, fontSize: 40 }}>
    {visual.items.slice(0, step + 1).map((tex, i) => { let html = null
      // KaTeX escapes its input (trust: false); unparseable TeX falls back to plain text.
      try { html = katex.renderToString(tex, { throwOnError: true, displayMode: true, trust: false }) } catch { html = null }
      return <Appear key={i} at={0}>{html ? <div style={{ opacity: i === step ? 1 : .55 }} dangerouslySetInnerHTML={{ __html: html }} />
        : <div style={{ fontFamily: 'monospace', opacity: i === step ? 1 : .55 }}>{tex}</div>}</Appear> })}
  </div>
}

function Bullets({ visual, step, at }) {
  return <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 22, maxWidth: 1000 }}>
    {visual.items.slice(0, step + 1).map((item, i) => <Appear key={i} at={at(i)}><li style={{ fontSize: 38, color: i === step ? C.ink : C.soft, display: 'flex', gap: 18 }}>
      <span style={{ color: C.teal, fontWeight: 800 }}>{String(i + 1).padStart(2, '0')}</span>{item}</li></Appear>)}
  </ul>
}

function Compare({ visual, step, at }) {
  const cell = { padding: '14px 20px', borderBottom: `2px solid ${C.line}`, fontSize: 28, textAlign: 'left' }
  return <table style={{ borderCollapse: 'collapse', minWidth: 820, background: '#fff', borderRadius: 14, overflow: 'hidden' }}>
    <thead><tr>{visual.headers.map((h, i) => <th key={i} style={{ ...cell, background: i ? C.teal : C.ink, color: '#fff' }}>{h}</th>)}</tr></thead>
    <tbody>{visual.rows.slice(0, step).map((row, r) => <Row key={r} row={row} cell={cell} at={at(r + 1)} />)}</tbody>
  </table>
}
function Row({ row, cell, at }) {
  return <tr style={{ opacity: useReveal(at) }}>{row.map((x, i) => <td key={i} style={{ ...cell, fontWeight: i ? 400 : 700 }}>{x}</td>)}</tr>
}

function ArrayView({ visual, step }) {
  const pointer = step > 0 ? visual.pointers[Math.min(step, visual.pointers.length) - 1] : null
  return <Cells items={visual.items} active={pointer?.index} note={pointer?.note} />
}

const VIEWS = { process: Flow, cycle: Flow, tree: Tree, plot: Plot, code_trace: CodeTrace, bullets: Bullets, compare: Compare, array: ArrayView, equation: Equation }

export function stepTotal(visual) {
  const k = visual.kind
  if (k === 'bullets' || k === 'equation') return visual.items.length
  if (k === 'compare') return 1 + visual.rows.length
  if (k === 'array' || k === 'code_trace') return 1 + (k === 'array' ? visual.pointers.length : visual.trace.length)
  if (k === 'plot') return 1 + 2 * visual.points.length + (visual.fit_line ? 1 : 0)
  return visual.nodes.length + 2 * visual.edges.length
}

export function LessonScene({ scene, cues, audio, index, total }) {
  const frame = useCurrentFrame(), { fps } = useVideoConfig(), t = frame / fps
  const current = cues.filter(c => c.start <= t).at(-1)
  const step = Math.min(stepTotal(scene.visual) - 1, current?.step ?? 0)
  const at = stepFrames(cues, fps)
  const View = VIEWS[scene.visual.kind] || Bullets
  const intro = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' })
  return <AbsoluteFill style={{ background: C.paper, color: C.ink, fontFamily: 'Inter, Segoe UI, system-ui, sans-serif', padding: '44px 64px', opacity: intro }}>
    {audio && <Audio src={audio} />}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `2px solid ${C.line}`, paddingBottom: 16 }}>
      <h1 style={{ margin: 0, fontSize: 50, fontWeight: 700, letterSpacing: -1 }}>{scene.title}</h1>
      <span style={{ fontSize: 24, color: C.soft }}>{String(index + 1).padStart(2, '0')} / {String(total).padStart(2, '0')}</span>
    </div>
    <div style={{ flex: 1, display: 'grid', placeItems: 'center', minHeight: 0 }}><View visual={scene.visual} step={step} at={at} /></div>
    <div style={{ borderTop: `2px solid ${C.line}`, paddingTop: 14, minHeight: 92 }}>
      <div style={{ fontSize: 20, color: C.teal, letterSpacing: 2, marginBottom: 6 }}>{scene.visual.caption.toUpperCase()}</div>
      <div style={{ fontSize: 30, lineHeight: 1.3 }}>{current?.text || ''}</div>
    </div>
  </AbsoluteFill>
}
