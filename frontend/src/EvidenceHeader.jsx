// ADR 0026 Epic 2 — the compact evidence header. One glance tells the reviewer HOW a finding was
// produced and what was measured: "Structural · Contrast 2.4:1 · Required 3:1 · Needs Review".
// Renders ONLY when the finding carries structured `evidence` from the detector (ADR 0016: a real
// number or nothing — this component never derives or invents a value from prose).
const METHOD_LABEL = {
  structural: 'Structural',
  'measured-pixels': 'Pixel Analysis',
  deterministic: 'Deterministic',
  ai: 'AI Proposal',
}

// 3.0 + ":1" → "3:1" · 2.4 + ":1" → "2.4:1" · 1.5 + "×" → "1.5×" · 4 + "%" → "4%"
// Exported so the coverage manifest can render the same measured value inline (one formatter,
// one rounding rule — the manifest and the header can never disagree).
export const fmtEvidence = (v, unit = '') => {
  const n = Number.isFinite(v) ? (Number.isInteger(v) ? v : +v.toFixed(2)) : v
  return unit === ':1' ? `${n}:1` : `${n}${unit}`
}
const fmt = fmtEvidence

export default function EvidenceHeader({ evidence, severity }) {
  if (!evidence || !evidence.method) return null
  const unit = evidence.unit || ''
  return (
    <div className="evheader" role="group" aria-label="How this finding was produced">
      <span className="evh-method">{METHOD_LABEL[evidence.method] || evidence.method}</span>
      {evidence.metric != null && evidence.value != null && (
        <span className="evh-item">{evidence.metric} <b>{fmt(evidence.value, unit)}</b></span>
      )}
      {evidence.required != null && (
        <span className="evh-item">Required <b>{fmt(evidence.required, unit)}</b></span>
      )}
      {severity === 'REVIEW' && <span className="evh-status">Needs Review</span>}
    </div>
  )
}
