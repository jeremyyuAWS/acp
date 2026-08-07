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

// Every (criterion, format) pair an operator may put in scope, with display labels —
// the universe the admin scope grid renders. A pair appears here only when the backend
// can reach a verdict on it (a pass/fail validator OR a review lane), so the grid can
// never offer a checkbox that would change nothing. Derived, so it cannot drift into
// claiming capability the engine does not have. `html` is excluded: this configures a
// DOCUMENT engagement.
export const SCOPE_UNIVERSE = [
  { sc: "1.1.1", name: "Non-text Content", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.3.1", name: "Info and Relationships", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.3.2", name: "Meaningful Sequence", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.3.3", name: "Sensory Characteristics", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.4.1", name: "Use of Color", level: "A", formats: ["docx", "pdf", "xlsx"] },
  { sc: "1.4.2", name: "Audio Control", level: "A", formats: ["pptx"] },
  { sc: "1.4.3", name: "Contrast (Minimum)", level: "AA", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.4.4", name: "Resize Text", level: "AA", formats: ["pptx"] },
  { sc: "1.4.5", name: "Images of Text", level: "AA", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.4.6", name: "Contrast (Enhanced)", level: "AAA", formats: ["pdf", "pptx", "xlsx"] },
  { sc: "1.4.8", name: "Visual Presentation", level: "AAA", formats: ["docx"] },
  { sc: "1.4.9", name: "Images of Text (No Exception)", level: "AAA", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "1.4.10", name: "Reflow", level: "AA", formats: ["docx", "pptx"] },
  { sc: "1.4.11", name: "Non-text Contrast", level: "AA", formats: ["docx", "pdf", "pptx"] },
  { sc: "1.4.12", name: "Text Spacing", level: "AA", formats: ["docx", "pdf", "pptx"] },
  { sc: "2.1.1", name: "Keyboard", level: "A", formats: ["pptx"] },
  { sc: "2.1.2", name: "No Keyboard Trap", level: "A", formats: ["docx", "pptx", "xlsx"] },
  { sc: "2.4.1", name: "Bypass Blocks", level: "A", formats: ["pdf"] },
  { sc: "2.4.2", name: "Page Titled", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "2.4.3", name: "Focus Order", level: "A", formats: ["pptx"] },
  { sc: "2.4.4", name: "Link Purpose (In Context)", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "2.4.6", name: "Headings and Labels", level: "AA", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "2.4.9", name: "Link Purpose (Link Only)", level: "AAA", formats: ["docx", "pptx"] },
  { sc: "2.4.10", name: "Section Headings", level: "AAA", formats: ["docx"] },
  { sc: "3.1.1", name: "Language of Page", level: "A", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "3.1.2", name: "Language of Parts", level: "AA", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "3.1.5", name: "Reading Level", level: "AAA", formats: ["docx", "pdf", "pptx", "xlsx"] },
  { sc: "3.3.2", name: "Labels or Instructions", level: "A", formats: ["docx"] },
  { sc: "4.1.2", name: "Name, Role, Value", level: "A", formats: ["docx", "pptx", "xlsx"] },
]

// The format columns the grid draws, in a fixed order so the header and every
// row line up regardless of which criteria happen to be selectable.
export const SCOPE_FORMATS = ["docx", "xlsx", "pptx", "pdf"]
