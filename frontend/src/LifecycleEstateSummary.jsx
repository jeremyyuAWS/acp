const SEGMENTS = [
  ['active', 'Active', 'Active'], ['already_archived', 'Already archived', 'already_archived'],
  ['archive_candidate', 'Archive candidate', 'Archive Candidate'], ['delete_candidate', 'Delete candidate', 'Delete Candidate'],
  ['deleted', 'Moved to source trash', 'Deleted'],
  ['exempt', 'Exempt / legal hold', 'Exempted'], ['reactivated', 'Reactivated', 'Reactivated'],
  ['unevaluable', 'Unevaluable / conflict', 'unevaluable'],
  ['failed', 'Source action failed', 'Failed'],
]
const COLORS = ['#4f772d', '#59636e', '#456990', '#a23e48', '#7f1d1d', '#8a6d1f', '#4d7c8a', '#6f4e7c', '#b91c1c']

export default function LifecycleEstateSummary({ summary, onSelect, onReview, onRules }) {
  if (!summary) return null
  const balanced = summary.total === summary.reconciled_total
  const integrity = summary.integrity
  const verified = integrity?.evidence_complete !== false
  return <section className="panel" aria-labelledby="lifecycle-estate-heading">
    <h2 id="lifecycle-estate-heading">Lifecycle estate summary</h2>
    <p role="status">{balanced ? `${summary.reconciled_total.toLocaleString()} of ${summary.total.toLocaleString()} files reconciled.` : `Reconciliation warning: ${summary.reconciled_total.toLocaleString()} of ${summary.total.toLocaleString()} files accounted for.`}</p>
    {!verified && <div role="alert" className="lifecycle-integrity-warning"><b>Lifecycle evidence incomplete.</b> {Number(integrity.candidate_count || 0).toLocaleString()} candidates were recorded, but only {Number(integrity.candidates_with_evidence || 0).toLocaleString()} have immutable rule evidence. Rerun Discovery after all workers are updated before relying on these recommendations.</div>}
    <div aria-hidden="true" style={{ display: 'flex', height: 14, borderRadius: 8, overflow: 'hidden', background: 'var(--line)' }}>
      {SEGMENTS.map(([key], index) => summary.counts[key] > 0 && <span key={key} style={{ width: `${summary.counts[key] / Math.max(1, summary.total) * 100}%`, background: COLORS[index] }} />)}
    </div>
    <table style={{ width: '100%', marginTop: 12 }}><caption className="sr-only">Lifecycle disposition counts</caption><tbody>
      {SEGMENTS.map(([key, label, status], index) => <tr key={key}>
        <td><span aria-hidden="true" style={{ color: COLORS[index] }}>●</span> {label}</td>
        {/* A count is a CONTROL only when somebody is listening. Discover no longer mounts the
            review queue these filtered, and a button that does nothing is worse than a figure:
            it is reachable by keyboard, announced as actionable, and answers nothing. */}
        <td style={{ textAlign: 'right' }}>{onSelect
          ? <button type="button" className="linklike" onClick={() => onSelect(status)}>{Number(summary.counts[key] || 0).toLocaleString()}</button>
          : Number(summary.counts[key] || 0).toLocaleString()}</td>
      </tr>)}
      <tr><th scope="row">Reconciled total</th><th style={{ textAlign: 'right' }}>{summary.reconciled_total.toLocaleString()}</th></tr>
    </tbody></table>
    <p><b>{summary.assessment_excluded.toLocaleString()}</b> disposition candidates marked outside Assess by default; some may also be unsupported file types.</p>
    <p className="muted">Recommendations only — no source files were moved or deleted.</p>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{onReview && <button type="button" onClick={onReview}>Review disposition queue</button>}{onRules && <button type="button" className="ghost" onClick={onRules}>View rule results</button>}</div>
  </section>
}
