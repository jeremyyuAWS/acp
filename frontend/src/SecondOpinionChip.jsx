// The escalation chip — "this LOW-confidence flag was checked a second time, off-box, by this
// model". Renders from `issue.hf_provenance`, the bounded record that
// _escalate_low_confidence_findings writes and issue_records.hf_provenance persists.
//
// WHY THE FINDING NEEDS IT. A LOW-confidence registration is one where the detector says so
// itself — PDF 1.3.5 matches field names against a vocabulary and cannot tell a personal address
// from a company one. When a vision model has looked at the rendered page as well, the reviewer
// is reading a different kind of claim than a bare heuristic hit, and nothing on the card said
// so: the escalation happened, cost money, and was invisible.
//
// WHAT IT DELIBERATELY DOES NOT SHOW. The model's answer. The provider returns free text about a
// page of a customer's document; none of it is stored (see _issue_provenance) and none of it is
// rendered. The chip is the FACT of the second reading, not its content — a reviewer who wants
// the reasoning re-reads the page, which is the honest thing to ask of them.
//
// Nothing rendered when nothing escalated, which is almost every finding.

// 🟢 local / 🟡 cloud, the same zone vocabulary as the AI provenance badge in Settings and the
// Evidence Card. An escalation is a cloud call by construction, but the zone is read rather than
// assumed — a provider that reports something else must not be drawn as if it were on-box.
const ZONE = {
  cloud: { glyph: '🟡', label: 'cloud' },
  local: { glyph: '🟢', label: 'local' },
}

// Two decimal places is not enough: one escalation is fractions of a cent, and rounding it to
// $0.00 turns a real charge into "free". Four keeps a single call legible without pretending to
// a precision the provider's own figure doesn't have.
export const fmtCost = (v) => (Number.isFinite(v) ? `$${v.toFixed(4)}` : null)

export default function SecondOpinionChip({ provenance }) {
  if (!provenance || !provenance.escalated) return null
  const provider = provenance.provider || 'a cloud model'
  const zone = ZONE[provenance.zone] || null
  const cost = fmtCost(provenance.cost_usd)
  // The cost is operational, not part of the accessibility judgement, so it lives in the title
  // rather than on the face of the card — available to anyone who asks, in nobody's way.
  const title = [
    `A second opinion was requested from ${provider}`,
    zone ? `processed ${zone.label}` : null,
    cost ? `cost ${cost}` : null,
  ].filter(Boolean).join(' · ')
  return (
    <span className="secondopinion" title={title}
          data-provider={provenance.provider || ''} data-zone={provenance.zone || ''}>
      {zone ? `${zone.glyph} ` : ''}⇗ second opinion · <b>{provider}</b>
    </span>
  )
}
