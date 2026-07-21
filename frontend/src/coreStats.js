import { allRules } from './rules'
import { DOCUMENTS_20 } from './documents20.js'
import { fmtOf, isAuto } from './capability.js'

// Document-core (DOCUMENTS_20) remediation stats over an estate, grounded in the remediation-
// capability table — the SAME lens the Assess tile leads with. Any surface that shows "criteria
// failed" or "% auto-fixable" reads it from here instead of re-deriving from the SIM-only `f.rec`,
// so the numbers reconcile with Assess exactly instead of quietly disagreeing (RiskScore used to
// count raw criteria and 0% automated where Assess showed the real core criteria + auto split).
//
// AssessRunner.computeResultFrom consumes this too (one formula, two consumers, no drift) — pinned
// by coreStats.test.js against a fixture and against AssessRunner's own numbers.

// A finding's `wcag` is EITHER the engine form 'SC_1_1_1' (real scans + SIM) or the axe-style
// '1.1.1 name'. Collapse both to the bare dotted SC so the two spellings never double-count.
// (Mirrors AssessRunner's local scOf.)
export const scOfWcag = (w) => ((String(w || '')).replace(/^SC_/, '').replace(/_/g, '.').match(/\d+\.\d+\.\d+/) || [])[0]

const RANK = { A: 1, AA: 2, AAA: 3 }
// Real scan findings carry no conformance level, so derive it from the SC catalog (rules/*.js meta).
const SC_LEVEL = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta.level]))
const levelOf = (x) => x.level || SC_LEVEL[scOfWcag(x.wcag)] || 'A'

// `cap` is the {fmt:{sc:mode}} capability map (fetched or CAPABILITY_FALLBACK). `level` is the
// conformance target — findings above it don't block and don't count, exactly like AssessRunner.
// Every DOCUMENTS_20 criterion is Level A/AA, so at the AA legal target the filter is a no-op and
// the counts are level-stable (which is why RiskScore, a fixed-AA leadership view, can call this
// with the default and still match an AA assessment).
export function coreStats(files, cap, level = 'AA') {
  const target = RANK[level] || RANK.AA
  let coreFindings = 0, coreAutoFix = 0
  const coreCriteria = new Set()
  ;(files || []).forEach((f) => {
    const fmt = fmtOf(f)
    ;(f.issues || []).forEach((x) => {
      if (RANK[levelOf(x)] > target) return
      const sc = scOfWcag(x.wcag)
      if (!sc || !DOCUMENTS_20.has(sc)) return
      coreFindings++
      coreCriteria.add(sc)
      if (isAuto(cap, fmt, sc)) coreAutoFix++
    })
  })
  return {
    coreFindings,
    coreCriteria: coreCriteria.size,
    coreAutoFix,
    coreHuman: coreFindings - coreAutoFix,
    // Share of core findings ACP can fix deterministically — the honest replacement for the
    // SIM-only rec.autoPct (which was a per-document routing ratio, 0 on real data).
    autoPct: coreFindings ? Math.round((coreAutoFix / coreFindings) * 100) : 0,
  }
}
