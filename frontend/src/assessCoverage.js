// Capability coverage — "what ACP can ASSESS, by file type" — decoupled from any one scan.
//
// The RuleBreakdown panel answers "what did THIS scan find" (from trace rows). This module
// answers the different, capability question the Assess tab needs up front: of the criteria
// that matter, which can ACP assess in the file types you actually have, which are buildable
// gaps, and which don't apply at all. It is computed from the same source-of-truth tables the
// backend uses (capability.js mirrors api/store.py), never from scan results — so a criterion
// ACP fully supports never looks like a hole just because an estate had no instances of it.
//
// Status of a criterion in ONE format:
//   auto  — assessed + deterministic remediation
//   ai    — assessed + AI-assisted (1-click) remediation
//   human — assessed, but remediation is human-authored (still detected)
//   gap   — applies to this format and is statically detectable, but ACP does not check it yet
//   at    — applies but needs interaction / assistive-tech testing (no static tool can prove it)
//   na    — the barrier cannot exist in this file type
// auto/ai/human = ASSESSABLE. gap = buildable. at/na = out of reach for static assessment.
import { CAPABILITY_FALLBACK as CAP, fmtOf } from './capability.js'
import { WCAG } from './wcagCatalog.js'

// The 20-check document core (US-regulated A/AA criteria that apply to documents).
export const DOCUMENTS_20 = ['1.1.1', '1.3.1', '1.3.2', '1.3.3', '2.4.6', '3.1.1', '3.1.2', '1.4.4', '1.4.5', '1.4.10', '1.4.12', '1.4.1', '1.4.3', '1.4.11', '2.4.2', '2.4.3', '2.4.4', '2.1.1', '2.1.2', '4.1.2']

// Buildable gaps — the barrier applies to the format and is statically detectable, ACP just
// doesn't check it there yet. A curated roadmap statement (not a fabricated capability claim):
// keep this honest and in step with what the engine actually ships.
// All buildable assessment gaps are now closed — ACP detects every statically-detectable
// criterion in every format (docx 1.3.2 · xlsx 2.4.4/2.4.6 · pdf 2.4.4/2.4.6 · html 1.3.2/1.4.5).
// The only criteria still uncovered are the keyboard ones (html 2.1.1/2.1.2), which no static
// tool can prove — those live in the AT set below, not here.
const GAP = new Set()
// Applies, but only provable by interaction / assistive-tech testing — never by static analysis.
const AT = new Set(['2.1.1|html', '2.1.2|html'])

export const GAP_REASON = {
  '1.3.2': 'Reading-order check not yet built for this format',
  '2.4.6': 'Heading / label check not yet built for this format',
  '2.4.4': 'Link-purpose check not yet built for this format',
  '1.4.5': 'Images-of-text detection not yet built for this format',
}
export const AT_REASON = 'Keyboard operability can only be verified by interaction / assistive-tech testing'

const NAME = Object.fromEntries(WCAG.map((c) => [c.sc, c.name]))
const LEVEL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))

// Status of a criterion in one format.
export function statusIn(sc, fmt) {
  const m = (CAP[fmt] || {})[sc]
  if (m === 'auto') return 'auto'
  if (m === 'assisted') return 'ai'
  if (m === 'human') return 'human'
  if (GAP.has(`${sc}|${fmt}`)) return 'gap'
  if (AT.has(`${sc}|${fmt}`)) return 'at'
  return 'na'
}

// Union status across the formats present in the estate — "assessable if we can assess it in
// ANY file type you have". Assessable beats gap beats needs-AT beats not-applicable.
const PRIORITY = ['auto', 'ai', 'human', 'gap', 'at', 'na']
export function statusAcross(sc, fmts) {
  const seen = fmts.map((f) => statusIn(sc, f))
  return PRIORITY.find((p) => seen.includes(p)) || 'na'
}

export const isAssessable = (s) => s === 'auto' || s === 'ai' || s === 'human'

// Which of the five formats are actually present in the estate (fallback: the four doc formats,
// so a pre-analysis or unknown estate still shows a sensible document-scoped view).
export function estateFormats(files) {
  const s = new Set()
  ;(files || []).forEach((f) => { const k = fmtOf(f); if (k) s.add(k) })
  const arr = [...s]
  return arr.length ? arr : ['docx', 'xlsx', 'pptx', 'pdf']
}

// The scorecard model: per-criterion status across the estate's formats, plus rolled-up counts.
// `documents` scopes to the 20-core; otherwise all document-applicable criteria in the catalog.
export function coverageSummary(files, { documents = true } = {}) {
  const fmts = estateFormats(files)
  const scs = documents ? DOCUMENTS_20 : WCAG.filter((c) => c.docApplies !== false).map((c) => c.sc)
  const per = scs.map((sc) => ({ sc, name: NAME[sc] || sc, level: LEVEL[sc] || '', status: statusAcross(sc, fmts) }))
  const n = (pred) => per.filter(pred).length
  return {
    fmts,
    per,
    total: scs.length,
    assessable: n((p) => isAssessable(p.status)),
    auto: n((p) => p.status === 'auto'),
    ai: n((p) => p.status === 'ai'),
    human: n((p) => p.status === 'human'),
    gap: n((p) => p.status === 'gap'),
    at: n((p) => p.status === 'at'),
    na: n((p) => p.status === 'na'),
  }
}
