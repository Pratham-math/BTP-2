export default function Readiness({ result, checking, onCheck, owner = true, disabled }) {
  return (
    <div className="readiness">
      <div className="readinessHead">
        <span>{checking ? 'Checking model and voice setup…' : result ? (result.ready ? 'Setup checks passed' : 'Setup needs attention') : 'Check model, narration and rendering setup'}</span>
        {owner && <button className="textButton" type="button" onClick={onCheck} disabled={checking || disabled}>Check setup</button>}
      </div>
      {result && <ul>{result.checks.map((check) => (
        <li key={check.name} className={check.ready ? 'checkReady' : 'checkMissing'}>
          <span aria-hidden="true">{check.ready ? '✓' : '!'}</span> {check.message}
          {!check.ready && check.action && <small>{check.action}</small>}
        </li>
      ))}</ul>}
    </div>
  )
}
