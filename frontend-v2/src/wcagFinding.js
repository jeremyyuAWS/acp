import { WCAG } from './wcagCatalog.js'
import { scOfWcag } from './coreStats.js'

// The one place a stored finding's `wcag` string becomes a criterion — its SC, its name and its
// conformance level.
//
// A finding's `wcag` arrives in three spellings, from three writers, in the same scan:
//
//   'SC_1_3_1'                      — the .NET/Office analyser and the SIM corpus
//   '1.3.1 Info and Relationships'  — the Python engine's axe-style label
//   '1.3.1'                         — bare, from the rule catalog
//
// Counting the raw string treats those as different criteria. On 2026-07-30 scan 12f28938cd2f
// carried two DOCX-HEAD-001 findings written 'SC_1_3_1' and one DOCX_PSEUDO_HEADING written
// '1.3.1 Info and Relationships', and the Overview's "Top WCAG violations" cloud duly showed
// BOTH "info & relationships" and "Info and Relationships" — one criterion, listed twice, its
// three findings split 2/1 across the two entries. Any "most common failure" read off that is
// wrong by construction.
//
// LEVEL is read from the catalog, not from the finding. Real scan findings carry NO `level`
// field at all — only SIM's corpus does — so `if (levelC[i.level] != null)` counted nothing on
// every real scan, and the "Findings by WCAG level" panel rendered its empty state, the words
// "No open findings.", beside a severity panel reporting six. A panel that cannot report bad
// news is not a healthy panel (#114); this one could not report any news.
//
// wcagCatalog is the authority here rather than rules/*.js: rules/ covers the criteria the
// FRONTEND engine has a detector for, and these findings come from the backend engines
// (OCR_IMAGE_OF_TEXT_STRICT, PDF_TIGHT_LINE_SPACING, DOCX-HEAD-001), which reach criteria
// rules/ has no module for. coreStats.levelOf falls back to 'A' for those, which would file
// 1.4.9 — a AAA criterion — under "Level A · must-have, the legal floor".

const BY_SC = Object.fromEntries(WCAG.map((c) => [c.sc, c]))

export { scOfWcag }

// The catalog entry for a finding, or null when the string names no criterion we know.
export const criterionOf = (wcag) => BY_SC[scOfWcag(wcag)] || null

// 'A' | 'AA' | 'AAA' | null. NEVER a default: a criterion we cannot place is unknown, and
// counting it as Level A would put an invented number under "the legal floor".
export const levelOfFinding = (f) => f?.level || criterionOf(f?.wcag)?.level || null

// The grouping key. Falls back to the raw string so a criterion the catalog has never heard of
// is still counted and still named — under-counting is the failure mode this module exists to
// stop, and silently dropping it would be a worse version of the same thing.
export const criterionKey = (wcag) => scOfWcag(wcag) || String(wcag || '').trim() || 'unknown'

// '1.3.1 Info and Relationships' — one spelling, whichever of the three came in.
export const criterionLabel = (wcag) => {
  const c = criterionOf(wcag)
  return c ? `${c.sc} ${c.name}` : criterionKey(wcag)
}

// The name alone, for a surface that renders the number separately (the word cloud).
export const criterionName = (wcag) => criterionOf(wcag)?.name || criterionKey(wcag)

// Count findings by criterion, collapsed across spellings. Returns [{sc, label, name, level,
// count}] sorted commonest first — one shape for the cloud, the export and the report.
export function findingsByCriterion(files) {
  const m = new Map()
  ;(files || []).forEach((f) => (f.issues || []).forEach((i) => {
    const key = criterionKey(i.wcag)
    const cur = m.get(key)
    if (cur) { cur.count += 1; return }
    m.set(key, { sc: key, label: criterionLabel(i.wcag), name: criterionName(i.wcag),
                 level: levelOfFinding(i), count: 1 })
  }))
  return [...m.values()].sort((a, b) => b.count - a.count || a.sc.localeCompare(b.sc))
}

// Findings per conformance level. Criteria the catalog cannot place are reported separately
// rather than folded into a level they might not belong to.
export function findingsByLevel(files) {
  const c = { A: 0, AA: 0, AAA: 0, unknown: 0 }
  ;(files || []).forEach((f) => (f.issues || []).forEach((i) => {
    c[levelOfFinding(i) || 'unknown'] += 1
  }))
  return c
}
