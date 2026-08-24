// The single per-(criterion × format) remediation-capability answer the UI consumes.
//
// Backed by api/remediation_capability.py (served at GET /capability). The frontend used to
// carry THREE disagreeing versions of this fact — AssessRunner's format-blind SC_AUTO and
// FileDrawer's hand-maintained REM_AUTOFIX_SC_BY_TYPE — which is exactly why the Assess tab
// could report "0 auto-fixable" on a docx that IS auto-fixable. Both should read from here.
//
// CAPABILITY_FALLBACK mirrors the Python table verbatim; it is the value used in SIM (no
// backend) and as the synchronous default before /capability resolves in real mode. The two
// are kept in lock-step by tests/test_capability_frontend_sync.py, which parses the JSON block
// below and asserts it equals remediation_capability.CAPABILITY.
//
// The table is DENSE — every in-scope (format, criterion) pair is listed, with its lane proven
// by a real remediate→re-scan round-trip in tests/test_remediation_capability.py. A pair absent
// from a format's map is out of scope for that format and treated as "human".
//
// Modes: "auto" (deterministic, no human), "assisted" (AI/OCR proposes, human approves),
// "human" (no automation / re-authoring — also the default for any absent criterion/format).

export const CAPABILITY_FALLBACK = {
  "docx": {
    "1.1.1": "assisted",
    "1.3.1": "auto",
    "1.3.2": "assisted",
    "1.3.3": "assisted",
    "1.4.1": "assisted",
    "1.4.3": "auto",
    "1.4.5": "assisted",
    "1.4.8": "assisted",
    "1.4.9": "assisted",
    "1.4.11": "assisted",
    "2.1.2": "human",
    "2.4.2": "auto",
    "2.4.4": "assisted",
    "2.4.6": "auto",
    "2.4.9": "assisted",
    "2.4.10": "assisted",
    "3.1.1": "auto",
    "3.1.2": "assisted",
    "3.1.5": "assisted",
    "3.3.2": "auto",
    "4.1.2": "auto"
  },
  "xlsx": {
    "1.1.1": "assisted",
    "1.3.1": "auto",
    "1.3.2": "auto",
    "1.3.3": "assisted",
    "1.4.1": "human",
    "1.4.3": "auto",
    "1.4.5": "assisted",
    "1.4.6": "auto",
    "1.4.9": "assisted",
    "1.4.11": "human",
    "2.4.2": "auto",
    "2.4.4": "assisted",
    "2.4.6": "assisted",
    "3.1.1": "auto",
    "3.1.2": "human",
    "3.1.5": "assisted",
    "4.1.2": "human"
  },
  "pptx": {
    "1.1.1": "assisted",
    "1.3.1": "auto",
    "1.3.2": "auto",
    "1.4.2": "assisted",
    "1.3.3": "assisted",
    "1.4.3": "auto",
    "1.4.5": "assisted",
    "1.4.6": "auto",
    "1.4.9": "assisted",
    "2.1.1": "human",
    "2.4.2": "auto",
    "2.4.4": "assisted",
    "2.4.6": "assisted",
    "2.4.9": "assisted",
    "3.1.1": "auto",
    "3.1.2": "assisted",
    "3.1.5": "assisted"
  },
  "pdf": {
    "1.1.1": "assisted",
    "1.3.1": "assisted",
    "1.3.2": "assisted",
    "1.3.3": "assisted",
    "1.4.3": "auto",
    "1.4.5": "assisted",
    "1.4.6": "auto",
    "1.4.9": "assisted",
    "2.4.1": "auto",
    "2.4.2": "auto",
    "2.4.3": "auto",
    "2.4.4": "human",
    "2.4.6": "assisted",
    "3.1.1": "auto",
    "3.1.2": "assisted",
    "3.1.5": "assisted",
    "4.1.2": "auto"
  },
  "html": {
    "1.1.1": "human",
    "1.2.1": "human",
    "1.2.2": "human",
    "1.2.3": "human",
    "1.3.1": "auto",
    "1.3.2": "human",
    "1.3.3": "assisted",
    "1.3.4": "auto",
    "1.3.5": "auto",
    "1.4.1": "auto",
    "1.4.2": "auto",
    "1.4.3": "auto",
    "1.4.4": "auto",
    "1.4.5": "human",
    "1.4.6": "auto",
    "1.4.10": "auto",
    "1.4.11": "human",
    "1.4.12": "auto",
    "2.4.1": "auto",
    "2.4.2": "auto",
    "2.4.3": "auto",
    "2.4.4": "assisted",
    "2.4.6": "auto",
    "2.4.7": "auto",
    "2.4.9": "human",
    "2.5.3": "auto",
    "2.5.8": "human",
    "3.1.1": "auto",
    "3.1.2": "assisted",
    "3.1.4": "auto",
    "3.1.5": "assisted",
    "3.3.2": "auto",
    "4.1.2": "auto"
  }
}

// The ASSESSMENT axis (ADR 0023) — "can ACP determine compliance?", independent of how a
// failure is remediated. Mirrors remediation_capability.assessment_table(); kept in lock-step
// by tests/test_capability_frontend_sync.py. Values: "auto" (🟢 ACP certifies pass & fail),
// "review" (🟡 ACP detects a likely issue, human confirms), "human" (🔴 ACP can't assess).
// A pair absent here is out of scope for that format → render a grey ⚪ N/A (not a verdict).
//
// The two axes really can disagree per cell, so read this table on its own rather than
// inferring it from the one above. pdf 4.1.2 is the clearest case: ⚡ auto to remediate (the
// fixer copies a meaningful field name into /TU deterministically) but 🟡 review to assess,
// because the detector reads AcroForm fields only and never the tagged-structure components
// 4.1.2 also covers — so a clean scan cannot certify it. Both literals below are strict JSON
// (no comments, no trailing commas): tests/test_capability_frontend_sync.py parses them with
// json.loads, and anything else makes the drift guard fail to read rather than fail to match.
export const ASSESSMENT_FALLBACK = {
  "docx": {
    "1.1.1": "review", "1.3.1": "auto", "1.3.2": "review", "1.3.3": "review", "1.4.1": "review",
    "1.4.3": "auto", "1.4.5": "review", "1.4.8": "auto", "1.4.9": "review", "1.4.11": "review",
    "2.1.2": "review", "2.4.2": "auto", "2.4.4": "review",
    "2.4.6": "review", "2.4.9": "review", "2.4.10": "review", "3.1.1": "auto", "3.1.2": "review",
    "3.1.5": "review", "3.3.2": "auto", "4.1.2": "review"
  },
  "xlsx": {
    "1.1.1": "review", "1.3.1": "auto", "1.3.2": "auto", "1.3.3": "review", "1.4.1": "review",
    "1.4.3": "auto", "1.4.5": "review", "1.4.6": "auto", "1.4.9": "review", "1.4.11": "review",
    "2.4.2": "auto", "2.4.4": "review", "2.4.6": "review", "3.1.1": "auto", "3.1.2": "review",
    "3.1.5": "review", "4.1.2": "review"
  },
  "pptx": {
    "1.1.1": "review", "1.3.1": "auto", "1.4.1": "review", "1.4.2": "review", "1.3.2": "auto",
    "1.3.3": "review", "1.4.3": "auto", "1.4.5": "review", "1.4.6": "auto", "1.4.9": "review",
    "2.1.1": "human", "2.4.2": "auto", "2.4.4": "review", "2.4.6": "review", "2.4.9": "review",
    "3.1.1": "auto", "3.1.2": "review", "3.1.5": "review"
  },
  "pdf": {
    "1.1.1": "review", "1.3.1": "review", "1.3.2": "review", "1.3.3": "review", "1.4.3": "auto",
    "1.4.5": "review", "1.4.6": "auto", "1.4.9": "review", "2.4.1": "auto", "2.4.2": "auto",
    "2.4.3": "review", "2.4.4": "review", "2.4.6": "review", "3.1.1": "auto", "3.1.2": "review",
    "3.1.5": "review", "4.1.2": "review"
  },
  "html": {
    "1.1.1": "review", "1.2.1": "review", "1.2.2": "review", "1.2.3": "review", "1.3.1": "auto",
    "1.3.2": "review", "1.3.3": "review", "1.3.4": "auto", "1.3.5": "auto", "1.4.1": "auto",
    "1.4.2": "auto", "1.4.3": "auto", "1.4.4": "auto", "1.4.5": "review", "1.4.6": "auto",
    "1.4.10": "auto", "1.4.11": "review", "1.4.12": "auto", "2.4.1": "auto", "2.4.2": "auto",
    "2.4.3": "auto", "2.4.4": "review", "2.4.6": "review", "2.4.7": "auto", "2.4.9": "review",
    "2.5.3": "auto", "2.5.8": "review", "3.1.1": "auto", "3.1.2": "review", "3.1.4": "auto",
    "3.1.5": "review", "3.3.2": "auto", "4.1.2": "auto"
  }
}

// Normalize a file object to one of the five capability formats, or null. Prefers the
// explicit type field (backend scans + SIM set file.type), falling back to the extension.
export const fmtOf = (file) => {
  const t = String(file?.type || '').toLowerCase()
  if (t === 'html' || t === 'htm') return 'html'
  if (['docx', 'pptx', 'xlsx', 'pdf'].includes(t)) return t
  const ext = String(file?.file || '').split('.').pop().toLowerCase()
  if (/^html?$/.test(ext)) return 'html'
  if (['docx', 'pptx', 'xlsx', 'pdf'].includes(ext)) return ext
  return null
}

// Recommendation POLICY, layered on top of the capability (not part of it): these criteria
// are technically auto-fixable where a remediator exists (capability "auto"), but the fix is
// a judgement call — recolouring text/brand colours — so the platform recommends a human
// confirm the result. It shifts wording and the recommended mode only; it never changes the
// capability mode (Assess + FileDrawer still count contrast auto-fixable). 1.4.3 Contrast
// (Minimum) + 1.4.6 Contrast (Enhanced). One definition, shared by sim.js's recommendation
// and FileDrawer's coverage table so they can't disagree.
export const REVIEW_RECOMMENDED_SC = new Set(['1.4.3', '1.4.6'])
export const reviewRecommended = (sc) => REVIEW_RECOMMENDED_SC.has(sc)

// cap here is the {fmt: {sc: mode}} map (fetched or the fallback). Any unknown (fmt, sc)
// is "human" — the conservative default, never a silent "auto".
export const modeFor = (cap, fmt, sc) => (cap && cap[fmt] && cap[fmt][sc]) || 'human'
export const isAuto = (cap, fmt, sc) => modeFor(cap, fmt, sc) === 'auto'

// Assessment axis (ADR 0023). `asmt` is the {fmt: {sc: lane}} assessment map (fetched
// `assessment` or ASSESSMENT_FALLBACK). Returns 'auto' | 'review' | 'human', or null when the
// pair is out of scope for that format — the caller renders null as a grey ⚪ N/A, NOT a verdict.
export const assessmentFor = (asmt, fmt, sc) => (asmt && asmt[fmt] && asmt[fmt][sc]) || null
export const autoSCs = (cap, fmt) => new Set(
  Object.entries((cap && cap[fmt]) || {}).filter(([, m]) => m === 'auto').map(([sc]) => sc)
)
