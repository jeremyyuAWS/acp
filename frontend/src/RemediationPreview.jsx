import { useState } from 'react'
import Thumbnail from './Thumbnail.jsx'
import { locationLabel } from './remediationInboxModel.js'
import { natureOf, contrastEvidence, metadataEvidence, readingOrderEvidence } from './remediationEvidence.js'
import GroundedBeforeAfter from './GroundedBeforeAfter.jsx'

// The third pane of the remediation workspace: a CONTEXTUAL PREVIEW of the actual document.
//
// The queue (left) says which finding, the guided card (centre) says what to do — this pane shows
// the reviewer the PROBLEM on the rendered page, with the flagged element boxed, and what the fix
// turns it into. "Show me the problem → show me the change" is half of the governing interaction.
//
// It is deliberately ADAPTIVE. A contrast or alt-text finding is a region of a page and renders
// beautifully; a missing document title or a reading-order problem is NOT visible on the rendered
// page at all, and pretending otherwise (a picture that shows nothing wrong) is worse than saying
// so. So a finding with no visual anchor gets an honest structure note instead of an empty frame.
//
// Null-safe throughout: with no scanId (SIM builds, tests) it shows the proposed change as text and
// a "connect a scan" note rather than calling the API — `Thumbnail` itself returns null on any
// render failure, so a missing preview is never a broken image or a layout hole.
//
// The preview also adapts by MODE, so the surface fits the KIND of finding rather than forcing every
// one through a page render:
//   • Visual     — the page/before-after preview above (unchanged), for findings you can point at.
//   • Properties — a metadata panel built ONLY from fields already on the finding (file, format,
//                  location, WCAG code, severity, source, before/after). Nothing is fetched or
//                  inferred; a field the finding doesn't carry is stated as unavailable, not guessed.
//   • Structure  — offered ONLY for a structure/metadata finding (missing title, reading order,
//                  language). It is an HONEST placeholder: the tag tree / reading order is computed
//                  during assessment and is NOT re-extracted for preview, so we say exactly that
//                  rather than draw a fabricated tree (ADR 0016 — never invent values).

const VIEWS = [['before', 'Before'], ['after', 'After'], ['both', 'Side by side']]

// A fix callout is grounded ONLY on REAL applied/verified state, never on a bare proposal (ADR 0016).
// `applied`/`autoApplied` (or an applied/approved/accepted status) mean the change was actually
// written to the document; `verified` means the confirming re-scan cleared the finding. A finding
// that merely carries a drafted `after` value is NOT applied — the After view already frames that as
// "applied on approval", so it gets no callout.
const APPLIED_STATUSES = new Set(['applied', 'approved', 'accepted', 'verified'])
const isFixApplied = (f) => !!(f?.applied || f?.autoApplied || APPLIED_STATUSES.has(String(f?.status || '').toLowerCase()))
const isReVerified = (f) => String(f?.status || '').toLowerCase() === 'verified'

// Small inline confirmations shown next to the fix — "✓ <what changed>", "✓ Re-scan cleared" — but
// ONLY when the finding records that the fix genuinely landed. Nothing here is fabricated: the "what
// changed" text is the finding's own applied `after` value, and "Re-scan cleared" appears only for a
// `verified` finding. No applied/verified state → this renders nothing (never a stock "Text color
// updated").
function FixCallouts({ f }) {
  if (!isFixApplied(f)) return null
  const after = f?.after ?? f?.proposals?.[0]?.proposed_value ?? null
  const chip = {
    display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600,
    padding: '3px 9px', borderRadius: 999, border: '1px solid var(--ok-line,#bfe3c9)',
    background: 'var(--ok-bg,#eafaef)', color: 'var(--ok-ink,#217a3b)',
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
      <span className="fix-callout" style={chip}>
        <span aria-hidden="true">✓</span> {after != null && after !== '' ? String(after) : 'Fix applied'}
      </span>
      {isReVerified(f) && (
        <span className="fix-callout" style={chip}><span aria-hidden="true">✓</span> Re-scan cleared</span>
      )}
    </div>
  )
}

// UI-only zoom of the rendered preview (mockup "− 100% +"). Purely presentational — it scales what is
// already on screen and fetches nothing, so it is honest to add regardless of the finding's data.
function Zoomable({ zoom, children }) {
  if (!zoom || zoom === 1) return children
  return (
    <div style={{ overflow: 'auto' }}>
      <div style={{ transform: `scale(${zoom})`, transformOrigin: 'top center', transition: 'transform .12s ease' }}>
        {children}
      </div>
    </div>
  )
}

// Whether we have COORDINATES to point at on the rendered page — a locator, an embedded-element
// thumb, or a page number. This is a data-availability question (can we draw a box / render the right
// page?), NOT the "is this visible?" question — that one is answered by the criterion's NATURE
// (remediationEvidence.natureOf). Keeping the two separate is the whole fix for the copy bug: a
// contrast finding with no locator is still a VISIBLE finding, just one we can't pinpoint.
function hasVisualAnchor(f) {
  return !!(f?.locator || f?.proposals?.[0]?.locator || f?.thumb || (f?.page != null && f?.page !== ''))
}
const localeOf = (f) => f?.locator || f?.proposals?.[0]?.locator || null

// The WCAG success-criterion the finding carries, normalised for display. `rule_id`/`ruleId` arrive
// as any of "WCAG_1.1.1", "SC_1.1.1", or a bare "1.1.1"; null when the finding names no criterion
// (we then omit the row rather than invent one).
function wcagCode(f) {
  const raw = f?.rule_id ?? f?.ruleId ?? null
  if (raw == null || raw === '') return null
  const sc = String(raw).replace(/^(WCAG_?|SC_)/i, '').replace(/_/g, '.')
  return sc ? `WCAG ${sc}` : null
}

function ProposedValue({ f }) {
  const after = f?.after ?? f?.proposals?.[0]?.proposed_value ?? null
  if (after == null || after === '') {
    return <p className="muted" style={{ fontSize: 13, margin: 0 }}>No drafted change — this finding is reviewed and, if needed, edited by a person.</p>
  }
  return (
    <div>
      <div style={{ border: '1px solid var(--line,#e2dce4)', borderRadius: 8, padding: '10px 12px', fontSize: 13.5, background: 'var(--surface-2,#f6f5f8)' }}>
        <span className="difftag">after</span> {String(after)}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        Applied to the document on approval, then re-validated by a fresh scan before it is certified.
      </p>
    </div>
  )
}

function Original({ f }) {
  // The ORIGINAL value to show — always `f.before` (the string). `beforeLiteral` is a boolean flag
  // (Remediate.jsx sets `!!firstBefore(it)`), so the old `beforeLiteral ?? before` rendered the flag
  // itself: "before true" when it had a literal, "before false" when it didn't — never the value.
  const before = f?.before ?? null
  if (before == null || before === '') return null
  return (
    <div style={{ border: '1px solid var(--line,#e2dce4)', borderRadius: 8, padding: '10px 12px', fontSize: 13.5, marginTop: 10 }}>
      <span className="difftag">before</span> {String(before)}
    </div>
  )
}

function PageView({ f, scanId }) {
  // The rendered page with the flagged element boxed (Thumbnail draws the measured bbox + zoom).
  // Real geometry only: for pptx/xlsx a resolvable locator yields a measured box + zoom-to-object
  // crop; for docx/pdf there is no per-element box, so we render the page (or, with no scan, an
  // honest note) — never a fabricated highlight.
  if (scanId && hasVisualAnchor(f)) {
    return (
      <div style={{ display: 'grid', placeItems: 'center' }}>
        <Thumbnail scanId={scanId} file={f.file} page={f.page || 1} locator={localeOf(f)} maxHeight={420} />
      </div>
    )
  }
  // The message depends on the criterion's NATURE, not on whether we have coordinates. A structural /
  // metadata finding genuinely isn't on the page; a visible finding we simply can't pinpoint is still
  // visible — so it must NOT be mislabelled "structure or metadata" (the copy bug this fixes).
  const structural = natureOf(f, hasVisualAnchor(f)) === 'structural'
  const message = structural
    ? 'This finding is about the document’s structure or metadata — it isn’t visible on the rendered page.'
    : hasVisualAnchor(f)
      ? 'A live page preview appears here when the workspace is connected to a scan.'
      : 'We can’t pinpoint this on the page automatically, but the change is shown below.'
  return (
    <div className="muted" style={{ display: 'grid', placeItems: 'center', textAlign: 'center', padding: '28px 18px',
                                    border: '1px dashed var(--line,#e2dce4)', borderRadius: 10, minHeight: 160 }}>
      <div>
        <div style={{ fontSize: 26 }} aria-hidden="true">{structural ? '⌘' : '🖼'}</div>
        <p style={{ margin: '8px 0 0', fontSize: 13 }}>{message}</p>
      </div>
    </div>
  )
}

// One label/value line in the Properties panel. A row with no value is stated as unavailable
// (muted em-dash) rather than dropped, so the reviewer can tell "not recorded" from "not shown".
function PropRow({ label, value, mono = false }) {
  const missing = value == null || value === ''
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '128px 1fr', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line,#e2dce4)' }}>
      <span className="muted" style={{ fontSize: 11.5, letterSpacing: '.04em', textTransform: 'uppercase' }}>{label}</span>
      {missing
        ? <span className="muted" style={{ fontSize: 13 }}>—</span>
        : <span style={{ fontSize: 13.5, minWidth: 0, overflowWrap: 'anywhere', fontFamily: mono ? 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)' : undefined }}>{String(value)}</span>}
    </div>
  )
}

// The metadata panel — every value here is a field already on the finding. No API, no inference.
function Properties({ f, fmt }) {
  const loc = locationLabel(f)
  const before = f?.before ?? null
  const after = f?.after ?? f?.proposals?.[0]?.proposed_value ?? null
  return (
    <div>
      <PropRow label="File" value={f?.file} />
      <PropRow label="Format" value={fmt} />
      <PropRow label="Location" value={loc} />
      <PropRow label="WCAG" value={wcagCode(f)} mono />
      <PropRow label="Severity" value={f?.severity} />
      <PropRow label="Source" value={f?.source} />
      <PropRow label="Current value" value={before} />
      <PropRow label="Proposed value" value={after} />
      <p className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
        Read directly from the finding — nothing here is fetched or inferred.
      </p>
    </div>
  )
}

// Structure mode — offered only for a structure/metadata finding. Deliberately does NOT draw a tag
// tree or reading-order diagram: that data is computed during assessment and not re-extracted for
// preview, so an invented one would be fiction (ADR 0016). We name the criterion and say so plainly.
function StructureNote({ f }) {
  const wcag = wcagCode(f)
  // A metadata finding (document title / language) DOES have a meaningful representation — the
  // property's real before→after value — so show that instead of the generic "not extracted" note.
  const meta = metadataEvidence(f)
  if (meta) {
    return (
      <div>
        <p className="muted" style={{ fontSize: 12.5, margin: '0 0 10px' }}>
          {wcag ? `${wcag} — ` : ''}A document property, not something on the rendered page. The change is to its value:
        </p>
        <GroundedBeforeAfter finding={f} />
      </div>
    )
  }
  // Reading order (1.3.2): the anchored items in the order a screen reader follows — a real,
  // meaningful structural representation, not the generic "not extracted" note.
  if (readingOrderEvidence(f)) {
    return (
      <div>
        <p className="muted" style={{ fontSize: 12.5, margin: '0 0 10px' }}>
          {wcag ? `${wcag} — ` : ''}Reading order — how a screen reader traverses the flagged anchored items:
        </p>
        <GroundedBeforeAfter finding={f} />
      </div>
    )
  }
  return (
    <div className="muted" style={{ display: 'grid', placeItems: 'center', textAlign: 'center', padding: '28px 18px',
                                    border: '1px dashed var(--line,#e2dce4)', borderRadius: 10, minHeight: 160 }}>
      <div style={{ maxWidth: 380 }}>
        <div style={{ fontSize: 26 }} aria-hidden="true">⌘</div>
        <p style={{ margin: '8px 0 0', fontSize: 13 }}>
          This is a document-structure finding{wcag ? ` (${wcag})` : ''} — a property like the document title,
          reading order or language, not something on a rendered page.
        </p>
        <p style={{ margin: '8px 0 0', fontSize: 12.5 }}>
          The structure was computed during assessment and is not yet extracted for preview here. Nothing
          is shown rather than a fabricated tag tree or reading order.
        </p>
      </div>
    </div>
  )
}

export default function RemediationPreview({ finding, scanId = null, embedded = false }) {
  const [mode, setMode] = useState('visual')
  const [view, setView] = useState('before')
  const [zoom, setZoom] = useState(1)

  if (!finding) {
    // Embedded in the workspace, the empty case is owned by the workspace (it shows the preview only
    // when a finding is selected), so render nothing rather than a second "select a finding" note.
    if (embedded) return null
    return (
      <div className="rem-prev" style={{ display: 'grid', placeItems: 'center', height: '100%', textAlign: 'center', padding: 24 }}>
        <p className="muted" style={{ fontSize: 13 }}>Select a finding to see it in the document.</p>
      </div>
    )
  }

  const fmt = String(finding.file || '').split('.').pop().toUpperCase()
  const sourceUrl = finding.sourceUrl || finding.source_url || null

  // Structure mode is offered ONLY when the finding really is a structure/metadata issue — judged by
  // the criterion's NATURE, not by whether we have coordinates. A contrast finding with no locator is
  // visible, not structural, so it does NOT get a Structure tab (and never the "structure or metadata"
  // copy). Adding Structure to a visible finding would promise a view we cannot honestly fill.
  const structural = natureOf(finding, hasVisualAnchor(finding)) === 'structural'
  // Grounded contrast evidence (real before/after colours) when the finding carries it — surfaced in
  // Visual mode so the reviewer SEES the change even with no page render (docx/pdf have no crop).
  const contrast = contrastEvidence(finding)
  const MODES = structural
    ? [['visual', 'Visual'], ['properties', 'Properties'], ['structure', 'Structure']]
    : [['visual', 'Visual'], ['properties', 'Properties']]
  // Guard against a stale mode if the selected finding changes shape (structure → visible): fall back
  // to Visual, which every finding supports.
  const activeMode = MODES.some(([m]) => m === mode) ? mode : 'visual'

  const zoomPct = Math.round(zoom * 100)
  const zoomBtn = { fontSize: 14, fontWeight: 700, lineHeight: 1, padding: '3px 10px', cursor: 'pointer', border: 'none', background: 'transparent', color: 'var(--ink)' }
  const zoomControl = (
    <div role="group" aria-label="Zoom" style={{ display: 'inline-flex', alignItems: 'center', border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
      <button type="button" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))}
              disabled={zoom <= 0.5} style={{ ...zoomBtn, opacity: zoom <= 0.5 ? 0.4 : 1 }}>−</button>
      <span aria-live="polite" style={{ fontSize: 12, fontWeight: 600, minWidth: 44, textAlign: 'center' }}>{zoomPct}%</span>
      <button type="button" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(2, Math.round((z + 0.25) * 100) / 100))}
              disabled={zoom >= 2} style={{ ...zoomBtn, opacity: zoom >= 2 ? 0.4 : 1 }}>+</button>
    </div>
  )

  const modeTabs = (
    <div role="tablist" aria-label="Preview mode" style={{ display: 'inline-flex', border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
      {MODES.map(([m, label]) => (
        <button key={m} role="tab" aria-selected={activeMode === m} onClick={() => setMode(m)}
                style={{ fontSize: 12, fontWeight: 600, padding: '4px 13px', cursor: 'pointer', border: 'none',
                         background: activeMode === m ? 'var(--ink)' : 'transparent', color: activeMode === m ? '#fff' : 'var(--ink)' }}>
          {label}
        </button>
      ))}
    </div>
  )

  // Folded into the remediation workspace as its Evidence section: no duplicate file header (the
  // workspace's Problem block names the file), no fixed height / internal scroll (the workspace
  // scrolls as one column), and Visual mode is the DOCUMENT view only — the before/after value diff
  // is shown once, in the workspace's "How to fix" section, so it is not repeated beneath the preview.
  if (embedded) {
    return (
      <div className="rem-prev rem-prev-embedded">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          {modeTabs}
          {activeMode === 'visual' && zoomControl}
        </div>
        <div style={{ marginTop: 12 }}>
          {activeMode === 'properties' && <Properties f={finding} fmt={fmt} />}
          {activeMode === 'structure' && <StructureNote f={finding} />}
          {activeMode === 'visual' && (
            <>
              <Zoomable zoom={zoom}><PageView f={finding} scanId={scanId} /></Zoomable>
              {contrast && <div style={{ marginTop: 12 }}><GroundedBeforeAfter finding={finding} scanId={scanId} /></div>}
              <FixCallouts f={finding} />
            </>
          )}
        </div>
        {sourceUrl && (
          <p style={{ margin: '10px 0 0' }}>
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="linklike" style={{ fontSize: 12.5 }}>Open original ↗</a>
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="rem-prev" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header — what we're looking at */}
      <div style={{ flex: '0 0 auto', padding: '12px 16px', borderBottom: '1px solid var(--line,#e2dce4)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
          <span style={{ fontWeight: 700, fontSize: 13.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {finding.file || 'Document'}
          </span>
          <span className="muted" style={{ fontSize: 12, flex: '0 0 auto' }}>{fmt}{locationLabel(finding) ? ` · ${locationLabel(finding)}` : ''}</span>
        </div>
        {/* Mode switcher — which KIND of surface fits this finding */}
        <div role="tablist" aria-label="Preview mode" style={{ display: 'inline-flex', marginTop: 10, border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
          {MODES.map(([m, label]) => (
            <button key={m} role="tab" aria-selected={activeMode === m} onClick={() => setMode(m)}
                    style={{ fontSize: 12, fontWeight: 600, padding: '4px 13px', cursor: 'pointer', border: 'none',
                             background: activeMode === m ? 'var(--ink)' : 'transparent', color: activeMode === m ? '#fff' : 'var(--ink)' }}>
              {label}
            </button>
          ))}
        </div>
        {/* Before / After / Side-by-side + zoom — only meaningful inside the Visual mode */}
        {activeMode === 'visual' && (
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
            <div role="tablist" aria-label="Preview view" style={{ display: 'inline-flex', border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
              {VIEWS.map(([v, label]) => (
                <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
                        style={{ fontSize: 12, fontWeight: 600, padding: '4px 13px', cursor: 'pointer', border: 'none',
                                 background: view === v ? 'var(--ink)' : 'transparent', color: view === v ? '#fff' : 'var(--ink)' }}>
                  {label}
                </button>
              ))}
            </div>
            {zoomControl}
          </div>
        )}
      </div>

      {/* Body — the adaptive preview */}
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: 16 }}>
        {activeMode === 'properties' && <Properties f={finding} fmt={fmt} />}
        {activeMode === 'structure' && <StructureNote f={finding} />}
        {activeMode === 'visual' && view === 'before' && (
          <>
            <Zoomable zoom={zoom}><PageView f={finding} scanId={scanId} /></Zoomable>
            <Original f={finding} />
          </>
        )}
        {activeMode === 'visual' && view === 'after' && (
          <Zoomable zoom={zoom}>
            <ProposedValue f={finding} />
            <FixCallouts f={finding} />
          </Zoomable>
        )}
        {activeMode === 'visual' && view === 'both' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: '0 0 6px' }}>Found</p>
              <Zoomable zoom={zoom}><PageView f={finding} scanId={scanId} /></Zoomable>
              <Original f={finding} />
            </div>
            <div>
              <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: '0 0 6px' }}>Proposed</p>
              <ProposedValue f={finding} />
              <FixCallouts f={finding} />
            </div>
          </div>
        )}
        {/* Grounded contrast swatches — the affected text at the real old vs new colour, on the real
            background, with the ratio computed from those colours. Shown in every Visual view because
            it IS the before→after, and it is the honest stand-in where docx/pdf have no page crop. */}
        {activeMode === 'visual' && contrast && (
          <div style={{ marginTop: 14 }}><GroundedBeforeAfter finding={finding} scanId={scanId} /></div>
        )}
      </div>

      {/* Footer — leave for the source document */}
      {sourceUrl && (
        <div style={{ flex: '0 0 auto', borderTop: '1px solid var(--line,#e2dce4)', padding: '10px 16px' }}>
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="linklike" style={{ fontSize: 12.5 }}>Open original ↗</a>
        </div>
      )}
    </div>
  )
}
