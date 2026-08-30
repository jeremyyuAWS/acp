import { SEV_DOT, SEV_LABEL } from './severityColors.js'
import { SEVERITIES } from './assessMetrics.js'

// A lightweight stand-in for the Assess tab while the full run/files payload is still loading —
// the same stale-while-revalidate idea OverviewPreviewCard.jsx applies to Overview, but scoped
// much more narrowly: Assess is not a pure dashboard. AssessSetup/AssessRunner run a real
// action (score the estate against WCAG) and AssessWorklist/AssessFileFindings drill into
// individual documents — none of that can work from GET /workspace/bootstrap's aggregate
// snapshot (`preview` here), which has counts only, no per-file rows. So this renders the
// numbers the snapshot DOES have — assessed count, avg score, severity mix — read-only, with no
// run button and no drill-in, and is swapped for the full functional Assess screen (App.jsx's
// `view === 'assess'` branch) the instant `run` arrives.
const tile = (v) => (v == null ? '—' : v.toLocaleString())

export default function AssessPreviewCard({ preview }) {
  if (!preview) return null
  const documents = preview.documents || {}
  const score = preview.score || {}
  const severity = preview.severity_distribution || {}
  const assessed = documents.assessed
  const assessable = preview.estate?.assessable
  const pct = (assessable && assessed != null) ? Math.round((100 * assessed) / assessable) : null
  const sevEntries = SEVERITIES.map((s) => [s, severity[s]]).filter(([, n]) => n != null && n > 0)

  return (
    <div className="panel" aria-busy="true">
      <h2 style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>Assessment summary</span>
        <span className="muted" style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 400 }}>
          <span className="spinner" aria-hidden="true" /> loading full detail…
        </span>
      </h2>
      <div className="metrics">
        <div className="metric">
          <span>assessed against WCAG</span>
          <b>{tile(assessed)}{pct != null ? ` (${pct}%)` : ''}</b>
        </div>
        <div className="metric"><span>certifiable</span><b>{tile(documents.certifiable)}</b></div>
        <div className="metric"><span>avg score</span><b>{score.avg != null ? `${Math.round(score.avg)}/100` : '—'}</b></div>
      </div>
      {sevEntries.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, marginTop: 4 }}>
          {sevEntries.map(([s, n]) => (
            <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', background: SEV_DOT[s] }} />
              {n.toLocaleString()} {SEV_LABEL[s].toLowerCase()}
            </span>
          ))}
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, margin: '10px 0 0' }}>
        Setup and per-document results become available once the full assessment loads.
      </p>
    </div>
  )
}
