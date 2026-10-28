const levels = { supportive: 'More support', balanced: 'Balanced', challenge: 'Extra challenge' }

export function AdaptiveStatus({ adaptivity, objectiveId }) {
  if (!adaptivity) return null
  const signal = adaptivity.understanding
  if (adaptivity.mode === 'reviewed_classroom') return <section className="panel adaptive-status"><h2>Teacher-reviewed learning</h2><p>Incorrect answers can lead to a reviewed recap and an equivalent check. This classroom does not generate unreviewed videos from your answers.</p></section>
  const future = (adaptivity.planned || []).filter(x => x.objective_id !== objectiveId).slice(0, 3)
  return <section className="panel adaptive-status" aria-label="Adaptive learning"><div className="row"><h2>Learning that adjusts to you</h2><span className="badge">{levels[signal.level] || 'Balanced'}</span></div>
    <p>{signal.observed_objectives ? `Learning signal: ${signal.score}/100 from ${signal.observed_objectives} assessed concept${signal.observed_objectives === 1 ? '' : 's'}.` : 'Starting with normal explanations while we gather assessment evidence.'}</p>
    <p className="muted">{signal.reason} This is a provisional teaching guide, not a grade or an ability diagnosis.</p>
    <p><strong>This explanation:</strong> {adaptivity.current_teaching ? levels[adaptivity.current_teaching.level] : 'Normal difficulty'}{adaptivity.current_teaching && ` · based on assessment ${adaptivity.current_teaching.assessment_number}`}</p>
    {future.length > 0 && <details><summary>Upcoming teaching plans</summary>{future.map(plan => <p key={plan.objective_id}>Block {plan.number}: {levels[plan.level]} · based on assessment {plan.based_on_assessment}</p>)}</details>}
    <p className="muted">{adaptivity.total_blocks <= adaptivity.lead_blocks ? `This lesson has ${adaptivity.total_blocks} blocks, so they use the initial normal explanations. Your answers still guide recaps and practice. Longer lessons adapt from block 4.` : `The first ${adaptivity.lead_blocks} blocks start normally. Assessment 1 shapes block 4, assessment 2 shapes block 5, and so on. Future blocks prepare in the background.`}</p>
  </section>
}
