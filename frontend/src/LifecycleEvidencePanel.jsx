export default function LifecycleEvidencePanel({ file }) {
  if (!file) return <div className="panel"><p>Select a file to inspect its lifecycle evidence.</p></div>
  return <section className="panel" aria-labelledby="lifecycle-evidence-heading">
    <h2 id="lifecycle-evidence-heading">Why this was recommended</h2>
    <p><b>{file.file}</b><br /><span className="muted">{file.path || 'Path not recorded'} · {file.lifecycle_status || 'Active'}</span></p>
    <p>{file.lifecycle_reason || 'No lifecycle reason was recorded.'}</p>
    {(file.evaluations || []).map((evaluation) => <details key={evaluation.evaluation_id} open={evaluation.policy_id === file.lifecycle_rule_id}>
      <summary>Policy {evaluation.policy_id} · version {evaluation.policy_version} · {evaluation.result}</summary>
      <ul>{(evaluation.evidence?.conditions || []).map((condition, index) => <li key={index}><b>{condition.field}</b>: actual {String(condition.observed_value ?? 'not recorded')} · required {condition.op} {String(condition.value ?? '')} — {condition.reason}</li>)}</ul>
    </details>)}
    <dl><dt>Owner</dt><dd>{file.owner || 'Not recorded'}</dd><dt>Last modified</dt><dd>{file.source_modified || 'Not recorded'}</dd><dt>Size</dt><dd>{file.size_kb == null ? 'Not recorded' : `${file.size_kb} KB`}</dd></dl>
    <p className="muted">Approval affects assessment scope and may queue a source action later. This review does not move or delete the source file.</p>
  </section>
}
