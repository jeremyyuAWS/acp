import { useState } from 'react'
import { getFilePdfContrast } from './api.js'

// ADR 0025 Tier B — the render-verified upgrade for the PDF 1.4.3 text-over-image finding. The scan
// flags "text sits over an image — the declared colour can't prove contrast"; on demand this renders
// the page (pdfium) and MEASURES the real text-vs-image contrast from the pixels, turning "unknowable
// from the file" into "measured X.X:1".
//
// Honesty (ADR 0016): REVIEW evidence, never a certified pass. A measured failure is concrete; a
// measured pass still says "looks legible — confirm" (a sampled ratio isn't a full audit). Busy
// photos / missing renderer say so plainly and the finding stays at its scan-time 🟡.
const REASON_TEXT = {
  render_unavailable: 'Page rendering isn’t available in this environment — verify by eye.',
  ambiguous_background: 'The image behind the text is too varied to measure a reliable contrast — verify by eye.',
  no_text_over_image: 'No text-over-image run found to measure.',
  render_failed: 'The page couldn’t be rendered — verify by eye.',
  source_unavailable: 'Source document not retrievable — verify by eye.',
  unsupported_format: 'This measurement applies to PDF only.',
  unavailable: 'Measurement not available here.',
  error: 'Couldn’t measure the contrast — verify by eye.',
}

export default function PdfImageContrastCheck({ scanId, file }) {
  const [state, setState] = useState('idle')   // idle | loading | done
  const [result, setResult] = useState(null)

  const run = () => {
    setState('loading')
    getFilePdfContrast(scanId, file).then((r) => {
      setResult(r || { measured: false, reason: 'error' })
      setState('done')
    })
  }

  if (state === 'idle') {
    return (
      <div className="hybridcontrast">
        <button type="button" className="linkbtn" onClick={run}
          title="Render the page and measure the real text/image contrast">
          ⧉ Measure contrast against the image
        </button>
      </div>
    )
  }
  if (state === 'loading') {
    return (
      <div className="hybridcontrast muted">
        <span className="spinner" style={{ width: 10, height: 10 }} /> Rendering the page and measuring…
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

  // Measured. Worst sampled ratio across the checked runs; a fail is the actionable signal.
  const { worst_ratio: worst, any_fail_aa: fail, checked, total } = result
  const bg = fail ? '#FAEEDA' : '#EEF4E4'
  const fg = fail ? '#854F0B' : '#3B6D11'
  return (
    <div className="hybridcontrast" role="status">
      <span className="dectag" style={{ background: bg, color: fg }}>
        {fail ? '⚠ measured' : '✓ measured'} {worst}:1
      </span>
      <span className="muted" style={{ marginLeft: 8 }}>
        {fail
          ? 'lowest sampled contrast over the image fails AA (needs 4.5:1) — fix or confirm it’s legible'
          : 'lowest sampled contrast over the image meets AA — looks legible, confirm'}
        {typeof checked === 'number' && total > checked ? ` · ${checked} of ${total} runs checked` : ''}
      </span>
    </div>
  )
}
