import { useState } from 'react'

export default function LifecycleRuleLedger({ rules = [], onSelect, integrity }) {
  const [open, setOpen] = useState(null)
  return <section className="panel" aria-labelledby="lifecycle-rule-heading">
    <h2 id="lifecycle-rule-heading">Rule results ledger</h2>
    {rules.length === 0 ? <p>{(integrity?.expected_rules || 0) > 0
      ? `${integrity.expected_rules} lifecycle rule${integrity.expected_rules === 1 ? '' : 's'} ran, but the immutable evaluation ledger was not recorded. Rerun Discovery before relying on these candidates.`
      : 'There were no enabled lifecycle rules in this recorded run.'}</p> : <div style={{ overflowX: 'auto' }}><table style={{ width: '100%' }}>
      <thead><tr><th>Rule</th><th>Priority</th><th>Evaluated</th><th>Matched</th><th>Skipped</th><th>Unevaluable</th><th>Conflicts</th><th>Proposed action</th></tr></thead>
      <tbody>{rules.map((rule) => <tr key={`${rule.policy_id}:${rule.policy_version}`}>
        <td><button type="button" className="linklike" aria-expanded={open === rule.policy_id} onClick={() => setOpen(open === rule.policy_id ? null : rule.policy_id)}>{rule.name}</button>{open === rule.policy_id && <div className="muted" style={{ marginTop: 6 }}>Policy {rule.policy_id} · immutable version {rule.policy_version} · evaluated {rule.evaluated_at ? new Date(rule.evaluated_at).toLocaleString() : 'time not recorded'}</div>}</td>
        <td>{rule.priority ?? '—'}</td><td>{rule.evaluated}</td>
        <td><button type="button" className="linklike" onClick={() => onSelect?.(rule.policy_id)}>{rule.matched}</button></td>
        <td>{rule.skipped}</td><td>{rule.unevaluable}</td><td>{rule.conflicts}</td><td>{rule.proposed_action}</td>
      </tr>)}</tbody>
    </table></div>}
    <p className="muted">A zero means the rule evaluated the recorded estate and matched zero files; skipped and missing-evidence counts remain visible separately.</p>
  </section>
}
