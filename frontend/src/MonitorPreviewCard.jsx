import { SEV_DOT, SEV_LABEL } from './severityColors.js'
import { SEVERITIES } from './assessMetrics.js'

// A lightweight stand-in for the Monitor tab while the full run/files payload is still loading —
// same stale-while-revalidate idea as OverviewPreviewCard.jsx/AssessPreviewCard.jsx, applied here
// too. Monitor mixes live/ambient content (QueuePanel, RevisionHistoryPanel — neither reads
// `run` at all) with per-scan compliance tracking (ComplianceDigest, RegressionRadar, the source
// watch/event stream — all of which need `run`/`files`), but App.jsx currently gates the WHOLE
// `<Monitor/>` mount behind `run`, so even the live parts sit behind the spinner unnecessarily.
// Splitting Monitor itself into a live-vs-per-scan layout is a separate, larger change; this is
// scoped narrowly, matching AssessPreviewCard: read-only compliance numbers from the cached
// snapshot, no controls, swapped for the full Monitor tab (which has its own further `assessed`
// gate — see App.jsx's `view === 'monitor'` branch — already handled, unaffected by this) the
// instant `run` arrives.
const tile = (v) => (v == null ? '—' : v.toLocaleString())

export default function MonitorPreviewCard({ preview }) {
  if (!preview) return null
  const documents = preview.documents || {}
  const score = preview.score || {}
  const severity = preview.severity_distribution || {}
  const sevEntries = SEVERITIES.map((s) => [s, severity[s]]).filter(([, n]) => n != null && n > 0)

  return (
    <div className="panel" aria-busy="true">
      <h2 style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>Compliance status</span>
        <span className="muted" style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 400 }}>
          <span className="spinner" aria-hidden="true" /> loading full detail…
        </span>
      </h2>
      <div className="metrics">
        <div className="metric"><span>avg score</span><b>{score.avg != null ? `${Math.round(score.avg)}/100` : '—'}</b></div>
        <div className="metric"><span>assessed</span><b>{tile(documents.assessed)}</b></div>
        <div className="metric"><span>certifiable</span><b>{tile(documents.certifiable)}</b></div>
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
        Source watch, the event stream, and drift tracking become available once the full scan loads.
      </p>
    </div>
  )
}
