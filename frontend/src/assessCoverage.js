// Capability coverage — "what ACP can ASSESS, by file type" — decoupled from any one scan.
//
// The RuleBreakdown panel answers "what did THIS scan find" (from trace rows). This module
// answers the different, capability question the Assess tab needs up front: of the criteria
// that matter, which can ACP assess in the file types you actually have, which are buildable
// gaps, and which don't apply at all. It is computed from the same source-of-truth tables the
// backend uses (capability.js mirrors api/remediation_capability.py), never from scan results
// — so a criterion ACP fully supports never looks like a hole just because an estate had no
// instances of it.
//
// TWO AXES (ADR 0023), resolved independently:
//
//   ASSESSMENT — "can ACP determine compliance?"  (assessmentIn)
//     auto   🟢 ACP certifies pass AND fail (deterministic/computable)
//     review 🟡 ACP detects evidence of a likely issue; a human confirms
//     human  🔴 ACP can't assess (author intent / runtime behaviour)
//     gap    — applies + statically detectable, ACP just doesn't check it yet (buildable)
//     at     — applies but only provable by interaction / assistive-tech testing
//     na     — the barrier can't exist in this file type (grey ⚪)
//
//   REMEDIATION — "if it fails, how is the fix produced?"  (remediationIn)
//     auto ⚡ deterministic · ai 🤖 AI proposes, human approves · human 👤 re-authoring · na —
//
// The axes are independent: e.g. 1.1.1 is 🟡 review + 🤖 AI; 2.4.2 is 🟢 auto + ⚡ automatic.
import { CAPABILITY_FALLBACK as REM, ASSESSMENT_FALLBACK as ASMT, fmtOf } from './capability.js'
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
// Review-only capability (ADR 0023): criteria ACP assesses via a REVIEW detector (evidence of a
// likely issue → human confirms) with no remediation lane, so they aren't in the CAPABILITY
// remediation table. Mirrors api/store.py REVIEW_FORMATS — the office interactive-control detector
// backs 2.1.2 (No Keyboard Trap) + 4.1.2 (Name/Role/Value). Per file these resolve to 🟡 only when
// controls are found; at the format level they mean "ACP has a review method here".
const REVIEW_ONLY = new Set([
  '2.1.2|docx', '2.1.2|pptx', '2.1.2|xlsx',   // interactive-control detector
  '4.1.2|docx', '4.1.2|pptx', '4.1.2|xlsx',
  '1.4.1|docx', '1.4.1|xlsx', '1.4.1|pdf',    // Use of Color — colour-only status / links (pdf: colour-only link)
  '2.4.3|pptx',                               // Focus Order — title not first
  '1.4.11|pptx', '1.4.11|docx', '1.4.11|pdf', // Non-text Contrast — faint shape outline
  // ADR 0024 Tier A — render-gated structural proxies. (1.4.3 hybrid is NOT here: 1.4.3 stays
  // 🟢 auto at the format level; its text-over-non-solid REVIEW is a per-file finding.)
  '1.4.4|pptx',                               // Resize Text — fixed-size text box
  '1.4.10|docx', '1.4.10|pptx',               // Reflow — table too wide
  '1.4.12|docx', '1.4.12|pptx', '1.4.12|pdf', // Text Spacing — exact line spacing (docx/pptx); tight line pitch (pdf)
])

export const GAP_REASON = {
  '1.3.2': 'Reading-order check not yet built for this format',
  '2.4.6': 'Heading / label check not yet built for this format',
  '2.4.4': 'Link-purpose check not yet built for this format',
  '1.4.5': 'Images-of-text detection not yet built for this format',
}
export const AT_REASON = 'Keyboard operability can only be verified by interaction / assistive-tech testing'

const NAME = Object.fromEntries(WCAG.map((c) => [c.sc, c.name]))
const LEVEL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))

// ASSESSMENT lane of a criterion in one format (🟢 auto / 🟡 review / 🔴 human / gap / at / na).
export function assessmentIn(sc, fmt) {
  const a = (ASMT[fmt] || {})[sc]
  if (a === 'auto') return 'auto'
  if (a === 'review') return 'review'
  if (a === 'human') return 'human'
  if (REVIEW_ONLY.has(`${sc}|${fmt}`)) return 'review'   // controls-gated review, no remediation lane
  if (GAP.has(`${sc}|${fmt}`)) return 'gap'
  if (AT.has(`${sc}|${fmt}`)) return 'at'
  return 'na'
}

// REMEDIATION lane of a criterion in one format (⚡ auto / 🤖 ai / 👤 human / — na).
export function remediationIn(sc, fmt) {
  const m = (REM[fmt] || {})[sc]
  if (m === 'auto') return 'auto'
  if (m === 'assisted') return 'ai'
  if (m === 'human') return 'human'
  return 'na'
}

// Back-compat: statusIn is the ASSESSMENT axis — the "can ACP assess this?" question this
// module is about. (Before the two-axis split it conflated assessment with remediation.)
export const statusIn = assessmentIn

// Union of a lane across the formats present in the estate — "the best we can do in ANY file
// type you have". Ordered best→worst for each axis; pass the resolver for the axis you want.
const ASSESS_PRIORITY = ['auto', 'review', 'human', 'gap', 'at', 'na']
const REM_PRIORITY = ['auto', 'ai', 'human', 'na']
export function statusAcross(sc, fmts, resolve = assessmentIn) {
  const order = resolve === remediationIn ? REM_PRIORITY : ASSESS_PRIORITY
  const seen = fmts.map((f) => resolve(sc, f))
  return order.find((p) => seen.includes(p)) || 'na'
}

// ACP produces SOMETHING on the assessment axis: a verdict (🟢) or an evidence-backed flag (🟡).
// 🔴 human / gap / at / na are not ACP assessments. `certifiable` is the honest headline: 🟢 only.
export const isAssessable = (s) => s === 'auto' || s === 'review'
export const isCertifiable = (s) => s === 'auto'

// Which of the five formats are actually present in the estate (fallback: the four doc formats,
// so a pre-analysis or unknown estate still shows a sensible document-scoped view).
export function estateFormats(files) {
  const s = new Set()
  ;(files || []).forEach((f) => { const k = fmtOf(f); if (k) s.add(k) })
  const arr = [...s]
  return arr.length ? arr : ['docx', 'xlsx', 'pptx', 'pdf']
}

// The scorecard model (ADR 0023): per-criterion status on BOTH axes across the estate's formats,
// plus rolled-up counts for each. `documents` scopes to the 20-core; otherwise all
// document-applicable criteria in the catalog. `status` is kept as an alias of `assessment` for
// back-compat with any un-migrated caller.
export function coverageSummary(files, { documents = true } = {}) {
  const fmts = estateFormats(files)
  const scs = documents ? DOCUMENTS_20 : WCAG.filter((c) => c.docApplies !== false).map((c) => c.sc)
  const per = scs.map((sc) => {
    const assessment = statusAcross(sc, fmts, assessmentIn)
    const remediation = statusAcross(sc, fmts, remediationIn)
    return { sc, name: NAME[sc] || sc, level: LEVEL[sc] || '', assessment, remediation, status: assessment }
  })
  const n = (pred) => per.filter(pred).length
  return {
    fmts,
    per,
    total: scs.length,
    // Assessment axis (🟢/🟡/🔴 + buildable/at/na).
    assessable: n((p) => isAssessable(p.assessment)),   // 🟢 + 🟡
    certifiable: n((p) => p.assessment === 'auto'),     // 🟢 only — the honest headline
    auto: n((p) => p.assessment === 'auto'),
    review: n((p) => p.assessment === 'review'),
    human: n((p) => p.assessment === 'human'),          // 🔴 can't-assess
    gap: n((p) => p.assessment === 'gap'),
    at: n((p) => p.assessment === 'at'),
    na: n((p) => p.assessment === 'na'),
    // Remediation axis (⚡/🤖/👤), counted over the criteria that carry a remediation lane.
    remAuto: n((p) => p.remediation === 'auto'),
    remAi: n((p) => p.remediation === 'ai'),
    remHuman: n((p) => p.remediation === 'human'),
    remNa: n((p) => p.remediation === 'na'),
  }
}

// Coverage gaps — the (criterion × format) cells where the barrier APPLIES to the format but ACP
// has NO assessment method: a buildable gap ('gap' — statically detectable, just not wired yet,
// reason in GAP_REASON) or an interaction / assistive-tech-only criterion ('at', reason AT_REASON).
// These are the only two "no method" states with an explanatory reason, and they are the honest
// definition of a coverage gap: a ⚪ N/A cell is NOT a gap (the barrier can't exist there) and a
// 🔴 human cell is the "a person must assess" lane (a method exists — it's a human), not a hole.
//
// Derived straight from assessmentIn over the estate's REAL formats (ADR 0016) — never fabricated.
// With today's capability tables GAP is empty (every statically-detectable document gap is closed)
// and AT holds only html 2.1.1/2.1.2, so a document-only estate honestly returns zero gaps and an
// estate that includes .html surfaces its two needs-AT keyboard criteria. `documents` scopes to
// the 20-core exactly as coverageSummary does.
export function assessmentGaps(files, { documents = true } = {}) {
  const fmts = estateFormats(files)
  const scs = documents ? DOCUMENTS_20 : WCAG.filter((c) => c.docApplies !== false).map((c) => c.sc)
  const byFormat = fmts.map((fmt) => {
    const criteria = scs
      .map((sc) => ({ sc, name: NAME[sc] || sc, level: LEVEL[sc] || '', lane: assessmentIn(sc, fmt) }))
      .filter((c) => c.lane === 'gap' || c.lane === 'at')
      .map((c) => ({ ...c, reason: c.lane === 'gap' ? (GAP_REASON[c.sc] || 'Not yet built for this format') : AT_REASON }))
    return { fmt, count: criteria.length, criteria }
  }).filter((g) => g.count > 0)
  return {
    fmts,
    byFormat,                                                   // only formats that actually have gaps
    total: byFormat.reduce((n, g) => n + g.count, 0),           // total gap CELLS across the estate
    cells: byFormat.flatMap((g) => g.criteria.map((c) => ({ ...c, fmt: g.fmt }))),
  }
}
