// Shared, PURE helpers for the reviewer's decision experience: classify a finding by the NATURE of
// its success criterion (is it something you can SEE on the page, or a structural/metadata property?)
// and, for contrast findings, turn the REAL before/after colour values into grounded evidence.
//
// Why this exists (the copy bug it fixes): the preview used to decide "visible vs. structure/metadata"
// from whether we happened to have coordinates (a locator / thumb / page). A 1.4.3 contrast finding in
// a .docx has none of those, so it was wrongly labelled "structure or metadata" — even though contrast
// is the most visual criterion there is. Nature is a property of the CRITERION, not of the geometry we
// managed to attribute, so it is classified here from the SC and used everywhere the UI must choose
// between "show me on the page" and "this isn't on the page".
//
// HONESTY (ADR 0016 — verify, don't fabricate): the contrast numbers here are the WCAG relative-
// luminance formula applied to the finding's OWN before/after hex values — the same maths the detector
// runs, on real data, never an invented ratio. When a colour or a background is not present in the
// finding we return null for that piece rather than guessing one, and the caller shows the swatch
// without a ratio instead of printing a fabricated "4.5:1".

import { scOf } from './fixSummary.js'

// The success criterion a finding names, as a bare dotted id ("1.4.3"), from any of the field
// spellings the pipeline uses. '' when the finding names no criterion.
export const findingSc = (f) => scOf(f?.rule_id ?? f?.ruleId ?? f?.wcag ?? '')

// SC → whether the finding is VISUAL (a reviewer can look at the page and judge it) or STRUCTURAL /
// metadata (a document property like the title, reading order or language, not a thing on the page).
// Deliberately small and explicit — an unlisted criterion is classified by the caller's data-
// availability fallback, so this map never has to be exhaustive to be correct for what it does list.
const SC_NATURE = {
  '1.1.1': 'visual',      // non-text content — the image itself is on the page
  '1.4.3': 'visual',      // contrast (minimum)
  '1.4.5': 'visual',      // images of text
  '1.4.6': 'visual',      // contrast (enhanced)
  '1.4.9': 'visual',      // images of text (no exception)
  '1.4.11': 'visual',     // non-text contrast
  '2.4.2': 'structural',  // page / document titled — metadata
  '1.3.1': 'structural',  // info & relationships — headings, table structure
  '1.3.2': 'structural',  // meaningful sequence — reading order
  '3.1.1': 'structural',  // language of page
  '3.1.2': 'structural',  // language of parts
}

// The nature declared for a criterion, or null when it is not one we classify.
export const natureOfSc = (sc) => SC_NATURE[sc] || null

// The nature of a finding. Classify by its criterion first; only when the criterion is unknown do we
// fall back to the old data-availability heuristic (a locator/thumb/page means "there's something to
// point at"). That fallback keeps un-mapped findings behaving exactly as before, while every mapped
// criterion is now judged by what it IS, not by whether we have coordinates for it.
export function natureOf(finding, hasAnchor = false) {
  const known = natureOfSc(findingSc(finding))
  if (known) return known
  return hasAnchor ? 'visual' : 'structural'
}

// The contrast criteria whose before/after values are colours we can render as grounded swatches.
const CONTRAST_SCS = new Set(['1.4.3', '1.4.6', '1.4.11'])
export const isContrastFinding = (f) => CONTRAST_SCS.has(findingSc(f))

// Every 6-digit hex colour in a string, in order ("#D9D9D9 on #FFFFFF" → ['#D9D9D9', '#FFFFFF']).
export function parseHexes(str) {
  return (String(str ?? '').match(/#[0-9a-fA-F]{6}\b/g) || []).map((h) => h.toUpperCase())
}

// WCAG relative luminance of one sRGB hex, and the contrast ratio between two — the exact formulae the
// detector uses. Real maths on the finding's real colours; nothing invented.
function channel(c) { const s = c / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4) }
function luminance(hex) {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16)
  if ([r, g, b].some((v) => Number.isNaN(v))) return null
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}
export function contrastRatio(fg, bg) {
  const L1 = luminance(fg), L2 = luminance(bg)
  if (L1 == null || L2 == null) return null
  const hi = Math.max(L1, L2), lo = Math.min(L1, L2)
  return (hi + 0.05) / (lo + 0.05)
}

// Display helpers for a computed ratio: "7.0:1", and the AA (4.5:1 normal-text) verdict. The verdict
// is derived from the real computed ratio against the published AA threshold — a fact, not a guess.
export const fmtRatio = (r) => (r == null ? null : `${r.toFixed(1)}:1`)
export const AA_RATIO = 4.5
export const passesAA = (r) => (r == null ? null : r >= AA_RATIO)

// Grounded contrast evidence built ONLY from the finding's real before/after values. Returns the
// foreground colours, a shared background (a contrast fix changes text colour, not the page), and the
// ratios COMPUTED from those real hexes — or null for any piece we cannot ground. null overall when
// this isn't a contrast finding or carries no parseable colour, so the caller falls back to text.
export function contrastEvidence(finding) {
  if (!isContrastFinding(finding)) return null
  const before = finding?.before
  const after = finding?.after ?? finding?.proposals?.[0]?.proposed_value ?? null
  const beforeHexes = parseHexes(before)
  const afterHexes = parseHexes(after)
  const fgBefore = beforeHexes[0] ?? null
  const fgAfter = afterHexes[0] ?? null
  // The background: the second colour in either value ("on #FFFFFF"). A contrast fix recolours the
  // text, so the same background applies to both states.
  const bg = beforeHexes[1] ?? afterHexes[1] ?? null
  if (!fgBefore && !fgAfter) return null
  const beforeRatio = fgBefore && bg ? contrastRatio(fgBefore, bg) : null
  const afterRatio = fgAfter && bg ? contrastRatio(fgAfter, bg) : null
  return { fgBefore, fgAfter, bg, beforeRatio, afterRatio }
}

// The plain-language "What ACP changed" sentence — real values only. For contrast it names the colour
// change and, when both ratios are grounded, the ratio change; otherwise it states the before→after
// value. null when the finding carries no proposed value to describe.
export function changeSentence(finding) {
  const ev = contrastEvidence(finding)
  if (ev && ev.fgBefore && ev.fgAfter) {
    let s = `Text color changed from ${ev.fgBefore} to ${ev.fgAfter}.`
    if (ev.beforeRatio != null && ev.afterRatio != null) {
      const dir = ev.afterRatio > ev.beforeRatio ? 'increased' : 'changed'
      s += ` Contrast ${dir} from ${fmtRatio(ev.beforeRatio)} to ${fmtRatio(ev.afterRatio)}.`
    }
    s += ' No text or layout changed.'
    return s
  }
  const before = finding?.before ?? null
  const after = finding?.after ?? finding?.proposals?.[0]?.proposed_value ?? null
  if (after == null || after === '') return null
  if (before != null && before !== '') return `Changed from “${String(before)}” to “${String(after)}”.`
  return `Proposed value: “${String(after)}”.`
}

// ── Alt text (1.1.1) ──────────────────────────────────────────────────────────────────────────
// The image is on the page and the fix is its alt string, so the evidence pairs the rendered image
// with the old vs new alt — both real (the finding carries the image and its before/after alt), never
// invented. Returns null (→ generic fallback) when this isn't an alt finding or nothing is proposed yet.
const ALT_SCS = new Set(['1.1.1'])
export const isAltTextFinding = (f) => ALT_SCS.has(findingSc(f))
export function altEvidence(finding) {
  if (!isAltTextFinding(finding)) return null
  const afterAlt = finding?.after ?? finding?.proposals?.[0]?.proposed_value ?? null
  if (afterAlt == null || afterAlt === '') return null
  const beforeAlt = finding?.before ?? null   // usually empty/absent — the missing alt IS the defect
  return { beforeAlt, afterAlt }
}

// ── Document metadata (2.4.2 title, 3.1.1/3.1.2 language) ─────────────────────────────────────
// A document PROPERTY, not something on the page — so #433 classifies it structural. Its evidence is
// the property's real before→after value (a labelled diff), which is the "meaningful representation,
// not an empty box" a structural finding should still show. null → generic fallback.
const METADATA_LABELS = { '2.4.2': 'Document title', '3.1.1': 'Language', '3.1.2': 'Language of parts' }
export const isMetadataFinding = (f) => !!METADATA_LABELS[findingSc(f)]
export function metadataEvidence(finding) {
  const label = METADATA_LABELS[findingSc(finding)]
  if (!label) return null
  const after = finding?.after ?? finding?.proposals?.[0]?.proposed_value ?? null
  if (after == null || after === '') return null
  return { label, before: finding?.before ?? null, after }
}

// ── Reading order (1.3.2) ─────────────────────────────────────────────────────────────────────
// The out-of-order floating items in DOCUMENT (anchor) order — the sequence a screen reader actually
// follows. Real data: propose_reading_order enqueues one proposal per floating box, in order, each
// carrying its own `text`; those land on the 1.3.2 finding's proposals. Returns the ordered texts, or
// null (→ the honest "not extracted" fallback) when none carry text.
export const isReadingOrderFinding = (f) => findingSc(f) === '1.3.2'
export function readingOrderEvidence(finding) {
  if (!isReadingOrderFinding(finding)) return null
  const props = Array.isArray(finding?.proposals) ? finding.proposals : []
  const items = props
    .slice()
    .sort((a, b) => (a?.seq ?? 0) - (b?.seq ?? 0))          // anchor order; falls back to array order
    .map((p) => (p && p.text != null ? String(p.text) : null))
    .filter((t) => t != null && t.trim() !== '')
  return items.length ? { items } : null
}
