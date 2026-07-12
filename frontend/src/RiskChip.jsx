import { reviewRisk } from './reviewRisk.js'

// The review risk tier + estimated effort for one finding (HITL vision #6). Lets a reviewer triage
// criticals or clear quick wins first. The title spells out the honest factors behind the tier.
export default function RiskChip({ item, compact = false }) {
  const r = reviewRisk(item)
  const f = r.factors
  const why = `${r.label} · ${f.reviewType === 'confirm' ? 'applied fix to confirm'
    : f.reviewType === 'author' ? 'manual authoring' : (f.grounded ? 'grounded AI proposal' : 'AI proposal to review')}`
    + ` · ${f.severity} severity · est ${r.estLabel} to review`
  return (
    <span title={why} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: compact ? '1px 8px' : '2px 10px',
      borderRadius: 20, fontSize: compact ? 11 : 12, fontWeight: 700,
      background: r.bg, color: r.color, border: `1px solid ${r.color}33`,
    }}>
      {r.label}
      <span style={{ fontWeight: 500, opacity: 0.85 }}>· est {r.estLabel}</span>
    </span>
  )
}
