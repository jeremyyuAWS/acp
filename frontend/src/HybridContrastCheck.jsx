import { useState } from 'react'
import { getFileContrast } from './api.js'

// ADR 0024 Tier B.1 — the render-verified upgrade for the 1.4.3 hybrid finding ("text over a
// picture/gradient fill"). On demand it renders the offending shapes and MEASURES the real WCAG
// contrast from the pixels, turning "contrast unknowable from the file" into "measured X.X:1".
//
// Honesty (ADR 0016): the result is REVIEW evidence, never a certified pass. A measured failure is
// concrete; a measured pass still says "looks legible — confirm" (a sampled ratio isn't a full
// per-run audit). When the pixels are ambiguous (busy photo) or rendering isn't available, it says
// so plainly and the finding stays at its Tier-A 🟡.
const REASON_TEXT = {
  render_unavailable: 'Layout rendering isn’t available in this environment — verify by eye.',
  ambiguous_background: 'Backgrounds too busy to measure a reliable contrast — verify by eye.',
  no_hybrid_shapes: 'No text-over-image shape found to measure.',
  source_unavailable: 'Source document not retrievable — verify by eye.',
  unsupported_format: 'Contrast can only be measured for slides.',
  unavailable: 'Measurement not available here.',
  error: 'Couldn’t measure the contrast — verify by eye.',
}

export default function HybridContrastCheck({ scanId, file }) {
  const [state, setState] = useState('idle')   // idle | loading | done
  const [result, setResult] = useState(null)

  const run = () => {
    setState('loading')
    getFileContrast(scanId, file).then((r) => {
      setResult(r || { measured: false, reason: 'error' })
      setState('done')
    })
  }

  if (state === 'idle') {
    return (
      <div className="hybridcontrast">
        <button type="button" className="linkbtn" onClick={run}
          title="Render the slides and measure the real text/background contrast">
          ⧉ Measure contrast from the rendered slides
        </button>
      </div>
    )
  }
  if (state === 'loading') {
    return (
      <div className="hybridcontrast muted">
        <span className="spinner" style={{ width: 10, height: 10 }} /> Rendering slides and measuring…
      </div>
    )
  }

  if (!result?.measured) {
    return (
      <div className="hybridcontrast muted" role="status">
        {REASON_TEXT[result?.reason] || REASON_TEXT.error}
      </div>
    )
  }

  // Measured. Worst sampled ratio across the checked shapes; a fail is the actionable signal.
  const { worst_ratio: worst, worst_shape: shape, any_fail_aa: fail, checked, total } = result
  const bg = fail ? 'var(--warn-bg)' : '#EEF4E4'
  const fg = fail ? 'var(--warn-fg)' : 'var(--success-fg)'
  return (
    <div className="hybridcontrast" role="status">
      <span className="dectag" style={{ background: bg, color: fg }}>
        {fail ? '⚠ measured' : '✓ measured'} {worst}:1
      </span>
      <span className="muted" style={{ marginLeft: 8 }}>
        {fail
          ? `lowest sampled contrast${shape ? ` (“${shape}”)` : ''} fails AA (needs 4.5:1) — fix or confirm it’s legible`
          : `lowest sampled contrast${shape ? ` (“${shape}”)` : ''} meets AA — looks legible, confirm`}
        {typeof checked === 'number' && total > checked ? ` · ${checked} of ${total} shapes checked` : ''}
      </span>
    </div>
  )
}
