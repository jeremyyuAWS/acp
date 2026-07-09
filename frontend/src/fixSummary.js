// Grouped fix summary — turns the REAL applied-fix records (remediation_diff, scan-wide)
// into the counts the reframed Remediation view shows: the hero "X issues fixed
// automatically", the grouped "Recent AI fixes" line, and the "Accessibility Improvements"
// impact tiles.
//
// Honesty first: every number here is a straight count of rows the pipeline actually wrote
// (a before→after record is only persisted for a fix that VERIFIABLY cleared on re-scan —
// see api/handlers.py `verified_diffs`). There is no fabricated total, no estimate, no
// fallback invented number. Empty input → empty output → the UI hides the surface rather
// than showing a zero dressed up as progress.

// Normalise any rule id form the backend hands us ("1.1.1", "SC_1_1_1", "WCAG_1_1_1") to a
// bare dotted success-criterion id.
export const scOf = (ruleId) =>
  String(ruleId || '').replace(/^(WCAG[_ ]?|SC[_ ]?)/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''

// SC → how we describe the fix in plain language. `countable` distinguishes "Added 14 image
// descriptions" (one per element) from mass-noun fixes like "Corrected reading order" (a
// document-level property). `category` collapses several SCs into one impact tile.
const GROUPS = {
  '1.1.1':  { category: 'Images',        verb: 'Added',     noun: 'image description', countable: true,  icon: '▦', order: 0 },
  '1.3.1':  { category: 'Tables',        verb: 'Added',     noun: 'table header',      countable: true,  icon: '⊞', order: 3 },
  '1.3.2':  { category: 'Reading order', verb: 'Corrected', noun: 'reading order',     countable: false, icon: '¶', order: 1 },
  '2.4.2':  { category: 'Titles',        verb: 'Added',     noun: 'document title',     countable: true,  icon: '¶', order: 2 },
  '2.4.4':  { category: 'Links',         verb: 'Corrected', noun: 'link description',   countable: true,  icon: '↗', order: 4 },
  '2.4.9':  { category: 'Links',         verb: 'Corrected', noun: 'link description',   countable: true,  icon: '↗', order: 4 },
  '2.4.6':  { category: 'Headings',      verb: 'Corrected', noun: 'heading',            countable: true,  icon: '¶', order: 2 },
  '3.1.1':  { category: 'Language',      verb: 'Set',       noun: 'document language',  countable: false, icon: '✦', order: 6 },
  '1.4.3':  { category: 'Contrast',      verb: 'Corrected', noun: 'contrast issue',     countable: true,  icon: '◑', order: 5 },
  '1.4.6':  { category: 'Contrast',      verb: 'Corrected', noun: 'contrast issue',     countable: true,  icon: '◑', order: 5 },
  '1.4.11': { category: 'Contrast',      verb: 'Corrected', noun: 'contrast issue',     countable: true,  icon: '◑', order: 5 },
}
const DEFAULT_GROUP = { category: 'Other', verb: 'Fixed', noun: 'issue', countable: true, icon: '◈', order: 9 }

export const groupMetaForSc = (sc) => GROUPS[sc] || DEFAULT_GROUP

const plural = (noun, n) => (n === 1 ? noun : `${noun}s`)

// The human sentence for one grouped fix entry, e.g. "Added 14 image descriptions" or
// "Corrected reading order" (mass nouns drop the count unless there were several places).
export function fixPhrase({ verb, noun, countable, count }) {
  if (countable) return `${verb} ${count} ${plural(noun, count)}`
  return count > 1 ? `${verb} ${noun} (${count} places)` : `${verb} ${noun}`
}

// Total real fixes = one row per verifiably-cleared before→after record.
export const totalFixes = (rows = []) => (Array.isArray(rows) ? rows.length : 0)

// Group real fix rows by success criterion → an ordered list for the "Recent AI fixes"
// summary. Each entry carries the plain-language `phrase` ("Added 14 image descriptions").
export function groupFixesByRule(rows = []) {
  const by = {}
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const sc = scOf(r.rule_id)
    if (!by[sc]) by[sc] = 0
    by[sc]++
  }
  return Object.entries(by)
    .map(([sc, count]) => {
      const m = groupMetaForSc(sc)
      return { sc, count, category: m.category, icon: m.icon, order: m.order,
               phrase: fixPhrase({ ...m, count }) }
    })
    .sort((a, b) => a.order - b.order || b.count - a.count)
}

// Collapse the per-SC groups into per-category impact counts for the "Accessibility
// Improvements" tiles: Images 14 · Reading order 6 · Tables 3 · Links 2 · Contrast 1.
export function summarizeImpact(rows = []) {
  const by = {}
  for (const g of groupFixesByRule(rows)) {
    if (!by[g.category]) by[g.category] = { category: g.category, count: 0, icon: g.icon, order: g.order }
    by[g.category].count += g.count
  }
  return Object.values(by).sort((a, b) => a.order - b.order || b.count - a.count)
}
