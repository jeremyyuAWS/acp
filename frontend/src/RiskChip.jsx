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
      {/* De-emphasised by WEIGHT, never by opacity. `opacity: 0.85` here blended the chip's own
          ink toward its own background — var(--error-fg) on #fbe7e2 renders as #bf5446, dropping 4.93:1
          to 3.85:1 and failing the 4.5:1 that 12px text requires. The colour was always fine;
          the transparency broke it. (WCAG 1.4.3 — the criterion this product certifies.) */}
      <span style={{ fontWeight: 500 }}>· est {r.estLabel}</span>
    </span>
  )
}
