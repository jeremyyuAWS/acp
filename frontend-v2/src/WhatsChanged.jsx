import { useState, useEffect } from 'react'
import { getScanDiff } from './api.js'

// "What's changed since your last scan" — a fast, scannable glance at estate drift, for
// the TOP of Overview. Distinct in purpose from ComplianceDigest (a narrated paragraph,
// tucked in Monitor) and RegressionRadar (the full per-file detail, also Monitor) — this
// is the landing-page teaser: a few numbers, each clickable, with a link out to the full
// picture. Reuses the same ADR 0009 scan-diff Dashboard's "Only new/changed" filter
// already fetches — no new backend. Renders nothing while loading or when there's no
// prior scan to compare against (first-ever scan), so it can't show a misleading "0s".
export default function WhatsChanged({ run, files, scanList = [], onPick, onGo }) {
  const curIdx = scanList.findIndex((s) => s.id === run.id)
  const prevScan = curIdx > -1 ? scanList[curIdx + 1] : undefined
  const [diff, setDiff] = useState(undefined)
  useEffect(() => {
    setDiff(undefined)
    if (!prevScan) { setDiff(null); return undefined }
    let alive = true
    getScanDiff(run.id, prevScan.id).then((d) => { if (alive) setDiff(d || null) }).catch(() => { if (alive) setDiff(null) })
    return () => { alive = false }
  }, [run.id, prevScan])

  if (!diff) return null
  const regressed = diff.regressed || [], improved = diff.improved || []
  const newFiles = diff.new || [], removedFiles = diff.removed || []
  // "Newly certified" = improved AND currently compliant — crosses into certifiable since
  // last scan, the single most motivating number here (vs. just "got a bit better").
  const improvedNames = new Set(improved.map((r) => r.file))
  const newlyCertified = files.filter((f) => improvedNames.has(f.file) && f.compliant)
  const scoreDelta = prevScan?.avg_score != null && run.avg_score != null ? run.avg_score - prevScan.avg_score : null
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'the prior scan')
  const byNames = (names) => files.filter((f) => names.has(f.file))

  const Stat = ({ n, label, color, names, fallbackFiles }) => (
    <button className="metric" style={{ textAlign: 'left', color: 'var(--ink)', cursor: n ? 'pointer' : 'default' }}
            disabled={!n}
            onClick={() => onPick?.({ title: label[0].toUpperCase() + label.slice(1), subtitle: `${n} document${n !== 1 ? 's' : ''} since ${fmtDate(diff.prev_at)}`, files: fallbackFiles || byNames(names) })}>
      <span>{label}</span><b style={{ color: n ? color : 'var(--muted)' }}>{n}</b>
    </button>
  )

  return (
    <section className="panel" style={{ borderLeft: '4px solid #6D28D9' }}>
      <h2>What's changed <span className="muted" style={{ fontWeight: 400 }}>· since {fmtDate(diff.prev_at)}</span></h2>
      <div className="metrics" style={{ margin: '10px 0' }}>
        {scoreDelta != null && (
          <div className="metric">
            <span>score</span>
            <b style={{ color: scoreDelta > 0 ? '#3B6D11' : scoreDelta < 0 ? '#B43A2A' : 'var(--ink)' }}>
              {scoreDelta > 0 ? `+${scoreDelta}` : scoreDelta === 0 ? '±0' : scoreDelta}
            </b>
          </div>
        )}
        <Stat n={regressed.length} label="regressed" color="#B43A2A" names={new Set(regressed.map((r) => r.file))} />
        <Stat n={improved.length} label="improved" color="#3B6D11" names={new Set(improved.map((r) => r.file))} />
        <Stat n={newlyCertified.length} label="newly certified" color="#3B6D11" fallbackFiles={newlyCertified} />
        <Stat n={newFiles.length} label="new documents" color="#1F5FA8" names={new Set(newFiles.map((r) => r.file))} />
        {removedFiles.length > 0 && (
          <div className="metric"><span>removed since last scan</span><b style={{ color: 'var(--muted)' }}>{removedFiles.length}</b></div>
        )}
      </div>
      {!regressed.length && !improved.length && !newFiles.length && (
        <p className="muted" style={{ margin: '4px 0 8px' }}>Nothing changed since the prior scan — the estate is stable.</p>
      )}
      {onGo && <button className="ghost small" onClick={() => onGo('monitor')}>View full digest &amp; regression detail →</button>}
    </section>
  )
}
