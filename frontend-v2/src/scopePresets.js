// GENERATED FILE — do not edit by hand.
//
// Source: SCOPE_PRESETS in api/store.py (defined in api/assessment_policy.py once #94 lands).
// Regenerate:  python scripts/gen_scope_presets.py
// Guarded by:  tests/test_scope_presets_frontend_sync.py  (CI fails on drift)
//
// An operator scope is the narrower of two different questions. RULE_FORMATS says which
// (criterion, format) pairs ACP *can* evaluate — a fact about the code. A scope preset says
// which of those the customer *asked* to have evaluated for this engagement — a choice. The
// backend gates on it inside `_rule_outcome`, so an out-of-scope pair reads NOT_EVALUATED in
// every stored trace; this file is the same list, for the surfaces that display it.

export const SCOPE_PRESETS = {
  "deva-final": {
    "1.1.1": ["docx", "pdf", "pptx", "xlsx"],
    "1.3.1": ["docx", "pdf", "pptx", "xlsx"],
    "1.3.2": ["pdf", "pptx"],
    "1.4.1": ["docx", "pdf", "pptx", "xlsx"],
    "1.4.3": ["docx", "pdf", "pptx", "xlsx"],
    "1.4.5": ["docx", "pdf", "pptx", "xlsx"],
    "2.1.1": ["pdf", "pptx"],
    "2.4.2": ["docx", "pdf", "pptx", "xlsx"],
    "2.4.3": ["pdf", "pptx"],
    "2.4.4": ["docx", "pdf", "pptx", "xlsx"],
    "2.4.6": ["docx", "pdf", "pptx", "xlsx"],
    "3.1.1": ["docx", "pdf", "pptx", "xlsx"],
    "3.1.2": ["docx", "pdf", "pptx", "xlsx"],
    "4.1.2": ["pdf"],
  },   // 14 criteria
}

// The criteria a preset covers, as a Set — the estate-level question ('is this
// criterion in scope at all'), as distinct from the per-format one below.
export const scopeCriteria = (name) => new Set(Object.keys(SCOPE_PRESETS[name] || {}))

// The per-(criterion, format) question, mirroring the backend's `in_scope()`: false only
// when a scope IS set and it excludes this pair. An unknown format is never excluded —
// the gate honours a deliberate choice, it does not invent one from an unparsed filename.
export const inScope = (name, sc, fmt) => {
  const scope = SCOPE_PRESETS[name]
  if (!scope) return true
  if (fmt == null) return true
  const fmts = scope[sc]
  return Boolean(fmts && fmts.includes(fmt))
}
