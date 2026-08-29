// A lightweight stand-in for Overview while the full run/files payload is still loading.
//
// GET /workspace/bootstrap's cached snapshot (`preview` here — the response's `overview` field,
// api/store.py get_overview_snapshot) has aggregate counts only, computed once per scan revision
// and cheap to serve — no per-file rows, so it cannot drive Overview.jsx itself (worklist links,
// department/source breakdowns, drill-in drawers all need `files`). Rendering it as its own small
// card, in place of the Loading spinner the Overview tab showed for the whole GET /scans/{id}
// duration, is the stale-while-revalidate half of the workspace-bootstrap redesign: real numbers
// the instant bootstrap resolves, swapped for the full Overview the instant the heavier call
// catches up (see App.jsx's `view === 'overview'` branch — this only ever renders before `run`
// is set for the first time; every subsequent scan switch already has `run`).
const tile = (v) => (v == null ? '—' : v.toLocaleString())

function lastUpdatedLabel(freshness) {
  const iso = freshness?.completed_at || freshness?.assessed_at || freshness?.discovered_at
  if (!iso) return null
  return new Date(iso).toLocaleString('en-US',
    { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export default function OverviewPreviewCard({ preview }) {
  if (!preview) return null
  const estate = preview.estate || {}
  const documents = preview.documents || {}
  const score = preview.score || {}
  const discovered = estate.discovered
  const assessed = documents.assessed
  const pct = (discovered && assessed != null) ? Math.round((100 * assessed) / discovered) : null
  const updated = lastUpdatedLabel(preview.freshness)

  return (
    <div className="panel" aria-busy="true">
      <h2 style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>Estate summary</span>
        <span className="muted" style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 400 }}>
          <span className="spinner" aria-hidden="true" /> loading full detail…
        </span>
      </h2>
      <div className="metrics">
        <div className="metric"><span>files discovered</span><b>{tile(discovered)}</b></div>
        <div className="metric">
          <span>assessed against WCAG</span>
          <b>{tile(assessed)}{pct != null ? ` (${pct}%)` : ''}</b>
        </div>
        <div className="metric"><span>certifiable</span><b>{tile(documents.certifiable)}</b></div>
        <div className="metric"><span>avg score</span><b>{score.avg != null ? `${Math.round(score.avg)}/100` : '—'}</b></div>
      </div>
      {updated && <p className="muted" style={{ fontSize: 12, margin: 0 }}>Last updated {updated}</p>}
    </div>
  )
}
