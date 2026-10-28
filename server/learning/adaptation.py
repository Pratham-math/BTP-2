"""Transparent formative-learning heuristic, not a calibrated ability test."""
import math

LEAD = 3
VERSION = 'rolling-understanding-v1'
TEACHING = {
    'supportive': 'Use small concrete inputs, explicit intermediate steps, brief prerequisite reminders and slower conceptual pacing. Explain one change per visual step. Keep all required objective content.',
    'balanced': 'Use the normal worked-example difficulty and a clear step-by-step explanation. Briefly revisit observed weak points without repeating mastered definitions.',
    'challenge': 'Reduce repetitive scaffolding and use a richer example or an in-scope transfer question. Explain the reasoning and edge cases. Never skip required concepts or introduce unassessed prerequisites.',
}


def bounded_score(value, fallback=0):
    return min(1., max(0., float(value))) if isinstance(value, (int, float)) and math.isfinite(value) else fallback


def understanding(evidence, objectives, *, through=None, target=None):
    rows = []
    for index, objective in enumerate(objectives):
        if through is not None and index > through:
            break
        entry = evidence.get(objective['id'], {})
        if not entry.get('attempts'):
            continue
        first = bounded_score(entry.get('first_score'), float(bool(entry.get('first_attempt_passed'))))
        latest = bounded_score(entry.get('latest_score'), float(entry.get('status') in {'passed', 'assisted'}))
        signal = .65 * first + .35 * latest
        signal -= min(.25, .08 * max(0, entry['attempts'] - 1))
        signal -= min(.24, .08 * entry.get('hints_used', 0))
        if entry.get('status') == 'assisted':
            signal = min(signal, .6)
        if entry.get('solution_shown'):
            signal = min(signal, .25)
        rows.append({'id': objective['id'], 'signal': max(0, signal), 'entry': entry})
    recent = rows[-5:]
    prerequisites = set(target.get('prerequisites', [])) if target else set()
    weights = [(index + 1) * (2 if row['id'] in prerequisites else 1) for index, row in enumerate(recent)]
    score = (.5 + sum(weight * row['signal'] for weight, row in zip(weights, recent))) / (1 + sum(weights))
    strong = sum(row['entry'].get('first_attempt_passed') is True and row['entry'].get('attempts') == 1
                 and not row['entry'].get('hints_used') and not row['entry'].get('solution_shown') for row in recent[-3:])
    struggling = any(row['entry'].get('status') in {'needs_revision', 'unresolved'} for row in recent[-2:])
    level = 'supportive' if rows and (score < .5 or struggling) else 'challenge' if score >= .8 and strong >= 2 else 'balanced'
    return {'version': VERSION, 'score': round(score * 100), 'level': level, 'observed_objectives': len(rows),
            'confidence': 'provisional' if len(rows) < 3 else 'developing', 'guidance': TEACHING[level],
            'reason': ('No assessment evidence yet; starting at normal difficulty.' if not rows else
                       'Recent checks suggest that more scaffolding would help.' if level == 'supportive' else
                       'Multiple independent first-attempt passes support a richer example.' if level == 'challenge' else
                       'Continue at normal difficulty while gathering more evidence.')}
