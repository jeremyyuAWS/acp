import { useEffect, useState } from 'react'
import { getScanStatus } from './api.js'

// ADR 0026 Epic 5 — the Confidence Dashboard: confidence in PROCESS, not a model %. Every tile is a
// real ratio shown WITH its counts (a percentage whose numerator and denominator are both visible is
// honest; "AI 97% sure" is not — ADR 0016). Reads the scan-scope Accessibility Status (the per-file
// models summed server-side), so these tiles can never disagree with the per-file cards.
const pct = (n, d) => (d > 0 ? Math.round((n / d) * 100) : 0)

const TILES = [
  { key: 'automatically_verified', label: 'Automatically Verified', cls: 'ok' },
  { key: 'human_verified', label: 'Human Verified', cls: 'ok' },
  { key: 'needs_review', label: 'Needs Review', cls: 'review' },
  { key: 'not_automatically_assessable', label: 'Not Automatically Assessable', cls: 'na' },
]

export default function ConfidenceDashboard({ scanId }) {
  const [m, setM] = useState(null)
  useEffect(() => {
    let live = true
    setM(null)
    getScanStatus(scanId).then((r) => { if (live) setM(r || { available: false }) })
    return () => { live = false }
  }, [scanId])

  if (!m || m.available === false) return null
  const unresolved = m.needs_review + m.needs_remediation + m.unapplied_approved
  return (
    <section className="confdash" aria-label="Assessment confidence — process coverage and resolution">
      <div className="confdash-head">
        <h4 className="drawerh" style={{ margin: 0 }}>Assessment Confidence</h4>
        <span className={`confdash-line ${unresolved === 0 ? 'ok' : 'review'}`}>
          {unresolved === 0
            ? '✓ No unresolved criteria'
            : `${unresolved} unresolved — ${[
                m.needs_review > 0 && `${m.needs_review} need review`,
                m.needs_remediation > 0 && `${m.needs_remediation} need remediation`,
                m.unapplied_approved > 0 && `${m.unapplied_approved} approved fixes not yet applied`,
              ].filter(Boolean).join(' · ')}`}
        </span>
      </div>
      <div className="confdash-tiles">
        <div className="confdash-tile">
          <span className="confdash-pct">{pct(m.coverage.evaluable, m.coverage.total)}%</span>
          <span className="confdash-lbl">Assessment Coverage</span>
          {/* The unit here is criterion CHECKS (criteria × documents), not WCAG criteria — 1,482
              dwarfs the 14/17/20 criteria totals elsewhere precisely because it is multiplied by
              the document count. Say "checks" so it doesn't read as a fifth, disagreeing criteria
              denominator. */}
          <span className="confdash-counts muted">{m.coverage.evaluable.toLocaleString()} of {m.coverage.total.toLocaleString()} criterion checks · {m.documents} document{m.documents !== 1 ? 's' : ''}</span>
        </div>
        {TILES.map((t) => (
          <div key={t.key} className={`confdash-tile ${t.cls}`}>
            <span className="confdash-pct">{pct(m[t.key], m.in_scope)}%</span>
            <span className="confdash-lbl">{t.label}</span>
            <span className="confdash-counts muted">{m[t.key]} of {m.in_scope}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
