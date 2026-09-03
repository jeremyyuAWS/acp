import { useState } from 'react'
import { getFileResize } from './api.js'

// ADR 0024 Tier B.2 — the render-verified upgrade for the 1.4.4 Resize Text finding (a fixed-size,
// auto-fit-off text box holding a lot of text). On demand it renders each box and MEASURES how much
// of it the text already fills. Enlarging text to 200% needs at least twice that height, so a box
// already over half full will overflow — turning "may clip at 200%" into "measured: fills X%".
//
// Honesty (ADR 0016): REVIEW evidence, never a certified pass. A measured overflow is confident; a
// box with headroom still says "verify" (rewrapping can still clip). Ambiguous / unrenderable →
// an honest note and the finding stays at its Tier-A 🟡.
const REASON_TEXT = {
  render_unavailable: 'Layout rendering isn’t available in this environment — verify by eye.',
  no_text_measured: 'Couldn’t isolate the text in the box to measure — verify by eye.',
  no_fixed_boxes: 'No fixed-size text box found to measure.',
  source_unavailable: 'Source document not retrievable — verify by eye.',
  unsupported_format: 'Fit can only be measured for slides.',
  unavailable: 'Measurement not available here.',
  error: 'Couldn’t measure the fit — verify by eye.',
}

const pct = (f) => `${Math.round(f * 100)}%`

export default function ResizeHeadroomCheck({ scanId, file }) {
  const [state, setState] = useState('idle')
  const [result, setResult] = useState(null)

  const run = () => {
    setState('loading')
    getFileResize(scanId, file).then((r) => {
      setResult(r || { measured: false, reason: 'error' })
      setState('done')
    })
  }

  if (state === 'idle') {
    return (
      <div className="resizecheck">
        <button type="button" className="linkbtn" onClick={run}
          title="Render the slides and measure how full each fixed-size text box is">
          ⧉ Measure whether the text fits at 200%
        </button>
      </div>
    )
  }
  if (state === 'loading') {
    return (
      <div className="resizecheck muted">
        <span className="spinner" style={{ width: 10, height: 10 }} /> Rendering slides and measuring fit…
      </div>
    )
  }
  if (!result?.measured) {
    return (
      <div className="resizecheck muted" role="status">
        {REASON_TEXT[result?.reason] || REASON_TEXT.error}
      </div>
    )
  }

  const { worst_fill: fill, worst_shape: shape, any_overflow_at_200: overflow, checked, total } = result
  const bg = overflow ? 'var(--warn-bg)' : '#EEF4E4'
  const fg = overflow ? 'var(--warn-fg)' : 'var(--success-fg)'
  const need = Math.min(200, Math.round(fill * 200))   // ≥2× the current fill, capped for display
  return (
    <div className="resizecheck" role="status">
      <span className="dectag" style={{ background: bg, color: fg }}>
        {overflow ? '⚠ measured' : '✓ measured'} fills {pct(fill)}
      </span>
      <span className="muted" style={{ marginLeft: 8 }}>
        {overflow
          ? `the fullest box${shape ? ` (“${shape}”)` : ''} needs ~${need}% of its height at 200% — text will clip; enlarge the box or shrink the content`
          : `the fullest box${shape ? ` (“${shape}”)` : ''} has headroom, but wrapping may still clip at 200% — verify`}
        {typeof checked === 'number' && total > checked ? ` · ${checked} of ${total} boxes checked` : ''}
      </span>
    </div>
  )
}
