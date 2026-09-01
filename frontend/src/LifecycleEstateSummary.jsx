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
  return <section className="panel" aria-labelledby="lifecycle-estate-heading">
    <h2 id="lifecycle-estate-heading">Lifecycle estate summary</h2>
    <p role="status">{balanced ? `${summary.reconciled_total.toLocaleString()} of ${summary.total.toLocaleString()} files reconciled.` : `Reconciliation warning: ${summary.reconciled_total.toLocaleString()} of ${summary.total.toLocaleString()} files accounted for.`}</p>
    <div aria-hidden="true" style={{ display: 'flex', height: 14, borderRadius: 8, overflow: 'hidden', background: 'var(--line)' }}>
      {SEGMENTS.map(([key], index) => summary.counts[key] > 0 && <span key={key} style={{ width: `${summary.counts[key] / Math.max(1, summary.total) * 100}%`, background: COLORS[index] }} />)}
    </div>
    <table style={{ width: '100%', marginTop: 12 }}><caption className="sr-only">Lifecycle disposition counts</caption><tbody>
      {SEGMENTS.map(([key, label, status], index) => <tr key={key}>
        <td><span aria-hidden="true" style={{ color: COLORS[index] }}>●</span> {label}</td>
        <td style={{ textAlign: 'right' }}><button type="button" className="linklike" onClick={() => onSelect?.(status)}>{Number(summary.counts[key] || 0).toLocaleString()}</button></td>
      </tr>)}
      <tr><th scope="row">Reconciled total</th><th style={{ textAlign: 'right' }}>{summary.reconciled_total.toLocaleString()}</th></tr>
    </tbody></table>
    <p><b>{summary.assessment_excluded.toLocaleString()}</b> disposition candidates excluded from Assess by default.</p>
    <p className="muted">Recommendations only — no source files were moved or deleted.</p>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button type="button" onClick={onReview}>Review disposition queue</button><button type="button" className="ghost" onClick={onRules}>View rule results</button></div>
  </section>
}
