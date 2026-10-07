export default function GenerationOptions({ selection, onChange, providers, runtime, disabled }) {
  const local = selection.mode === 'local'
  const defaults = providers?.defaults || {
    local: { mode: 'local', text_model: 'qwen3:4b-q4_K_M', voice: 'en_US-lessac-medium', speech_rate: 1 },
    cloud: { mode: 'cloud', text_model: '', voice: 'Kore', speech_rate: 1 },
  }
  const models = providers?.ollama?.models || []
  const voices = providers?.piper?.voices || []
  const modelIds = [...new Set([selection.text_model, ...models.map((m) => m.id)].filter(Boolean))]
  const voiceIds = [...new Set([selection.voice, ...voices.map((v) => v.id)].filter(Boolean))]
  return (
    <div className="generationOptions">
      <fieldset className="modePicker" disabled={disabled}>
        <legend>Generation mode</legend>
        {['local', 'cloud'].map((mode) => (
          <label key={mode} className={selection.mode === mode ? 'selected' : ''}>
            <input type="radio" name="generation-mode" value={mode} checked={selection.mode === mode}
              onChange={() => onChange({ ...defaults[mode], render_profile: selection.render_profile })} />
            {mode === 'local' ? (runtime?.personal_session ? 'Run on this laptop' : 'Local model on the server') : 'Use cloud API'}
          </label>
        ))}
      </fieldset>
      <p className="computeNote">Three scenes · Rendered on {runtime?.host || 'the backend computer'}.</p>
      {local && (
        <div className="optionGrid">
          <label>Ollama model
            <select value={selection.text_model} disabled={disabled} onChange={(e) => onChange({ ...selection, text_model: e.target.value })}>
              {modelIds.map((id) => <option key={id} value={id}>{id}{!models.some((m) => m.id === id) ? ' (not installed)' : ''}</option>)}
            </select>
          </label>
          <label>Piper voice
            <select value={selection.voice} disabled={disabled} onChange={(e) => onChange({ ...selection, voice: e.target.value })}>
              {voiceIds.map((id) => <option key={id} value={id}>{id}{!voices.some((v) => v.id === id) ? ' (not installed)' : ''}</option>)}
            </select>
          </label>
        </div>
      )}
      <label className="qualityField">Video quality
        <select value={selection.render_profile} disabled={disabled} onChange={(e) => onChange({ ...selection, render_profile: e.target.value })}>
          <option value="720p24">720p · 24 fps</option><option value="480p24">480p preview · 24 fps</option>
        </select>
      </label>
      <p className="computeNote">{local ? 'Ollama writes the script and Piper creates narration. Setup requires installed model and voice files.' : 'The prompt and narration are sent to Gemini. Rendering stays on the backend computer.'}</p>
    </div>
  )
}
