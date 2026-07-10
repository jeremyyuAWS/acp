// The single per-(criterion × format) remediation-capability answer the UI consumes.
//
// Backed by api/remediation_capability.py (served at GET /capability). The frontend
// used to carry THREE disagreeing versions of this fact — AssessRunner's format-blind
// SC_AUTO and FileDrawer's hand-maintained REM_AUTOFIX_SC_BY_TYPE — which is exactly why
// the Assess tab could report "0 auto-fixable" on a docx that IS auto-fixable. Both now
// read from here instead.
//
// CAPABILITY_FALLBACK mirrors the Python table verbatim; it is the value used in SIM (no
// backend) and as the synchronous default before /capability resolves in real mode. The
// two are kept in lock-step by tests/test_capability_frontend_sync.py, which parses the
// JSON block below and asserts it equals remediation_capability.CAPABILITY.
//
// Modes: "auto" (deterministic, no human), "assisted" (AI proposes, human approves),
// "human" (no automation — also the default for any absent criterion/format).

export const CAPABILITY_FALLBACK = {
  "html": {
    "3.1.1": "auto",
    "2.4.2": "auto",
    "1.3.1": "auto",
    "1.4.3": "auto",
    "1.4.10": "auto",
    "1.4.4": "auto",
    "1.4.12": "auto",
    "1.4.2": "auto",
    "1.3.4": "auto",
    "1.3.5": "auto",
    "1.4.1": "auto",
    "2.4.1": "auto",
    "2.4.3": "auto",
    "2.4.6": "auto",
    "2.4.7": "auto",
    "2.5.3": "auto",
    "3.1.4": "auto",
    "1.1.1": "assisted",
    "2.4.4": "assisted"
  },
  "docx": {
    "2.4.2": "auto",
    "1.3.1": "auto",
    "2.4.6": "auto",
    "1.4.3": "auto",
    "1.1.1": "assisted"
  },
  "pptx": {
    "3.1.1": "auto",
    "2.4.2": "auto",
    "1.3.2": "auto",
    "1.1.1": "assisted"
  },
  "xlsx": {
    "3.1.1": "auto",
    "2.4.2": "auto",
    "1.4.3": "auto",
    "1.3.1": "auto",
    "1.3.2": "auto",
    "1.1.1": "assisted"
  },
  "pdf": {
    "3.1.1": "auto",
    "2.4.2": "auto",
    "1.1.1": "assisted",
    "1.3.2": "assisted"
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

// cap here is the {fmt: {sc: mode}} map (fetched or the fallback). Any unknown (fmt, sc)
// is "human" — the conservative default, never a silent "auto".
export const modeFor = (cap, fmt, sc) => (cap && cap[fmt] && cap[fmt][sc]) || 'human'
export const isAuto = (cap, fmt, sc) => modeFor(cap, fmt, sc) === 'auto'
export const autoSCs = (cap, fmt) => new Set(
  Object.entries((cap && cap[fmt]) || {}).filter(([, m]) => m === 'auto').map(([sc]) => sc)
)
