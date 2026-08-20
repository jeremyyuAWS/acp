import { contrastEvidence, altEvidence, metadataEvidence, readingOrderEvidence, fmtRatio, passesAA } from './remediationEvidence.js'
import Thumbnail from './Thumbnail.jsx'

// The honest "before → after" the reviewer judges a remediation-inbox fix by. This is the piece the
// redesign is built around: hex values and ratios PROVE the rule passed, but they don't let a normal
// reviewer see that the document still LOOKS acceptable. So for a contrast finding we render the
// affected text at the OLD vs the NEW colour, on the finding's real background, with the ratio
// computed from those real colours — a picture of the change, grounded entirely in the finding's own
// data (ADR 0016). For any other finding we fall back to the literal before → after values.
//
// It carries NO invented geometry: there is no per-element crop for docx/pdf here (api/geometry.py
// returns None for those), so a highlighted crop would be fabricated. The pptx/xlsx crop lives in
// Thumbnail.jsx, surfaced by the preview pane where a real bounding box exists.
//
// (Distinct from BeforeAfterEvidence.jsx, which drives the EvidenceCard surface off a `card` prop and
// a detail-string parse. This one works from a remediation-inbox finding's before/after fields.)

function Swatch({ label, color, bg, ratio }) {
  const passes = passesAA(ratio)
  return (
    <div style={{ flex: '1 1 0', minWidth: 0 }}>
      <p className="muted" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', margin: '0 0 6px' }}>{label}</p>
      <div style={{ border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ background: bg || '#ffffff', color: color || '#000', padding: '16px 12px',
                      fontSize: 15, fontWeight: 600, textAlign: 'center', lineHeight: 1.3 }}>
          The quick brown fox
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
                      padding: '6px 10px', borderTop: '1px solid var(--line,#e2dce4)', background: 'var(--surface-2,#f6f5f8)' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: 3, border: '1px solid var(--line,#e2dce4)', background: color || 'transparent', flex: '0 0 auto' }} />
            <span style={{ fontFamily: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)' }}>{color || '—'}</span>
          </span>
          {ratio != null && (
            <span style={{ fontSize: 12, fontWeight: 700, color: passes ? 'var(--ok-ink,#217a3b)' : 'var(--bad-ink,#a33b28)' }}>
              {fmtRatio(ratio)} · {passes ? 'Passes' : 'Fails'}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function TextState({ label, value, tag }) {
  const missing = value == null || value === ''
  return (
    <div style={{ flex: '1 1 0', minWidth: 0 }}>
      <p className="muted" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', margin: '0 0 6px' }}>{label}</p>
      <div style={{ border: '1px solid var(--line,#e2dce4)', borderRadius: 8, padding: '10px 12px', fontSize: 13.5,
                    background: tag === 'before' ? 'transparent' : 'var(--surface-2,#f6f5f8)' }}>
        {missing ? <span className="muted">—</span> : String(value)}
      </div>
    </div>
  )
}

export default function GroundedBeforeAfter({ finding, scanId = null }) {
  const ev = contrastEvidence(finding)
  if (ev) {
    return (
      <div className="ba-evidence ba-contrast">
        <div style={{ display: 'flex', gap: 12, alignItems: 'stretch', flexWrap: 'wrap' }}>
          <Swatch label="Before" color={ev.fgBefore} bg={ev.bg} ratio={ev.beforeRatio} />
          <span aria-hidden="true" style={{ flex: '0 0 auto', alignSelf: 'center', fontSize: 18, color: 'var(--muted,#8a8f98)' }}>→</span>
          <Swatch label="After" color={ev.fgAfter} bg={ev.bg} ratio={ev.afterRatio} />
        </div>
        <p className="muted" style={{ fontSize: 11.5, margin: '8px 0 0' }}>
          {/* Sample text, NOT the document's real run: a docx/pdf contrast finding carries the colour
              VALUES, not the affected text, so we must not imply this is the document's own words. */}
          Sample text at the old and new text color.
          {ev.bg != null
            ? ' Shown on the document’s real background.'
            : ' Contrast ratio isn’t shown — the finding didn’t record the background color.'}
        </p>
      </div>
    )
  }
  // Alt text (1.1.1): the affected image beside its old vs new alt. The image is the real render
  // (Thumbnail — cropped to the flagged object where a bounding box exists, the plain page otherwise;
  // it never invents a location); the alt strings are the finding's own before/after.
  const alt = altEvidence(finding)
  if (alt) {
    return (
      <div className="ba-evidence ba-alt" style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {scanId && finding?.file && (
          <div style={{ flex: '0 0 auto', maxWidth: 180 }}>
            <Thumbnail scanId={scanId} file={finding.file} page={finding.page || 1}
                       locator={finding.locator || finding.proposals?.[0]?.locator || null} maxHeight={140} />
          </div>
        )}
        <div style={{ flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <TextState label="Alt text — before" value={alt.beforeAlt == null || alt.beforeAlt === '' ? '(no alt text)' : alt.beforeAlt} tag="before" />
          <TextState label="Alt text — after" value={alt.afterAlt} tag="after" />
        </div>
      </div>
    )
  }

  // Document metadata (title / language): the property's real before → after value — a meaningful
  // representation of a structural finding, not an empty "it isn't on the page" box.
  const meta = metadataEvidence(finding)
  if (meta) {
    return (
      <div className="ba-evidence ba-meta" style={{ display: 'flex', gap: 12, alignItems: 'stretch', flexWrap: 'wrap' }}>
        <TextState label={`${meta.label} — before`} value={meta.before == null || meta.before === '' ? '(not set)' : meta.before} tag="before" />
        <span aria-hidden="true" style={{ flex: '0 0 auto', alignSelf: 'center', fontSize: 18, color: 'var(--muted,#8a8f98)' }}>→</span>
        <TextState label={`${meta.label} — after`} value={meta.after} tag="after" />
      </div>
    )
  }

  // Reading order (1.3.2): the out-of-order floating items as a numbered sequence — the real order a
  // screen reader follows, from the finding's own proposals (each carries its text). No fabricated
  // full-document sequence; only the items the detector actually flagged, in their anchor order.
  const ro = readingOrderEvidence(finding)
  if (ro) {
    return (
      <div className="ba-evidence ba-reading-order">
        <p className="muted" style={{ fontSize: 11.5, margin: '0 0 8px' }}>
          The order a screen reader reads these anchored items — each is spoken at its anchor, not its visual position:
        </p>
        <ol style={{ margin: 0, paddingLeft: 22, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {ro.items.map((t, i) => (
            <li key={i} style={{ fontSize: 13.5, border: '1px solid var(--line,#e2dce4)', borderRadius: 8, padding: '8px 10px', listStylePosition: 'outside' }}>{t}</li>
          ))}
        </ol>
      </div>
    )
  }

  // Non-contrast: the literal before → after the finding carries (e.g. old vs new alt text, a title).
  const before = finding?.before ?? null
  const after = finding?.after ?? finding?.proposals?.[0]?.proposed_value ?? null
  return (
    <div className="ba-evidence ba-text" style={{ display: 'flex', gap: 12, alignItems: 'stretch', flexWrap: 'wrap' }}>
      <TextState label="Before" value={before} tag="before" />
      <span aria-hidden="true" style={{ flex: '0 0 auto', alignSelf: 'center', fontSize: 18, color: 'var(--muted,#8a8f98)' }}>→</span>
      <TextState label="After" value={after} tag="after" />
    </div>
  )
}
