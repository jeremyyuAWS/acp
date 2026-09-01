export default function LifecycleEvidencePanel({ file }) {
  if (!file) return <div className="panel"><p>Select a file to inspect its lifecycle evidence.</p></div>
  return <section className="panel lifecycle-evidence-panel" aria-labelledby="lifecycle-evidence-heading">
    <h2 id="lifecycle-evidence-heading">Why this was recommended</h2>
    <p><b>{file.file}</b><br /><span className="muted">{file.path || 'Path not recorded'} · {file.lifecycle_status || 'Active'}</span></p>
    <p>{file.lifecycle_reason || 'No lifecycle reason was recorded.'}</p>
    {(file.evaluations || []).map((evaluation) => <details key={evaluation.evaluation_id} open={evaluation.policy_id === file.lifecycle_rule_id}>
      <summary>Policy {evaluation.policy_id} · version {evaluation.policy_version} · {evaluation.result}</summary>
      <ul>{(evaluation.evidence?.conditions || []).map((condition, index) => <li key={index}><b>{condition.field}</b>: actual {String(condition.observed_value ?? 'not recorded')} · required {condition.op} {String(condition.value ?? '')} — {condition.reason}</li>)}</ul>
    </details>)}
    <dl><dt>Owner</dt><dd>{file.owner || 'Not recorded'}</dd><dt>Last modified</dt><dd>{file.source_modified || 'Not recorded'}</dd><dt>Size</dt><dd>{file.size_kb == null ? 'Not recorded' : `${file.size_kb} KB`}</dd></dl>
    <LifecycleTimeline events={file.history} />
    <p className="muted">Approval affects assessment scope and may queue a source action later. This review does not move or delete the source file.</p>
  </section>
}

// PRD §7.4: "timeline of prior scans, recommendations, overrides, approvals, and source
// actions". Rendered as an ordered list rather than a styled rail so a screen reader gets the
// sequence and its length for free — the order IS the information here.
const KIND = {
  evaluated: 'Recommended', override: 'Kept by a reviewer',
  approval: 'Approval', decision: 'Recorded',
}

function LifecycleTimeline({ events }) {
  // Three distinct states, never collapsed into one empty box: not asked for, asked for and
  // unreadable, and genuinely nothing recorded. Only the third is good news.
  if (events === undefined) return null
  if (events === null) {
    return <section aria-labelledby="lifecycle-history-heading">
      <h3 id="lifecycle-history-heading" style={{ fontSize: 13 }}>History</h3>
      <p role="status">The history for this document could not be read. The evidence above is unaffected.</p>
    </section>
  }
  return <section aria-labelledby="lifecycle-history-heading">
    <h3 id="lifecycle-history-heading" style={{ fontSize: 13 }}>History</h3>
    {events.length === 0
      ? <p>No earlier lifecycle activity was recorded for this document.</p>
      : <ol>{events.map((event, index) => <li key={`${event.ts || 'undated'}:${index}`}>
        <b>{KIND[event.kind] || event.kind}</b>
        {' · '}{event.ts ? new Date(event.ts).toLocaleString() : 'date not recorded'}
        {event.scan_id && <> · scan {event.scan_id}</>}
        {event.policy_id && <> · {event.policy_id}
          {event.policy_version != null && <> v{event.policy_version}</>}</>}
        {event.actor && <> · {event.actor}</>}
        {event.detail && <><br /><span className="muted">{event.detail}</span></>}
      </li>)}</ol>}
  </section>
}
