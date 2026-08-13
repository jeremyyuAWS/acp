import { SCOPE_PRESETS, scopeCriteria, inScope as presetInScope } from './scopePresets.js'
import { DOCUMENTS_20 } from './documents20.js'

// The one place the SPA answers "which criteria is this engagement scoped to".
//
// THREE DIFFERENT DENOMINATORS are visible across the product for "how many criteria apply",
// and until this module they were three unlabelled numbers that read as three disagreeing
// measurements of one quantity:
//
//   ~38  TRACED       — criteria ACP recorded an outcome for on this file's FORMAT. A fact about
//                       the code (per-format catalog size), counted from stored traces. Answers
//                       "did ACP look?". Shown by the Accessibility Status card and the
//                       Confidence Dashboard, which already label it "traced".
//    20  DOCUMENT CORE — the curated document-applicable A/AA set the product certifies against
//                       (`documents20.js`). A product decision. Answers "what does ACP certify?".
//    14  AGREED SCOPE  — the subset the customer put in scope for THIS engagement
//                       (`SCOPE_PRESETS`, server-side). A customer choice. Answers "what did we
//                       agree to assess?".
//
// They are legitimately different questions, so none of them is wrong. What was wrong was
// showing them unlabelled on one screen. Every surface that renders one of these totals now
// names which it is using — see DENOMINATOR below.
//
// The scope list itself is NOT retyped here: `scopePresets.js` is generated from the backend's
// SCOPE_PRESETS by scripts/gen_scope_presets.py, and CI fails on drift. This module only
// decides which preset is active and derives the display arithmetic from it.

// The preset in force. THE SERVER DECIDES THIS — see applyScopeConfig() below. The literal here
// is only the pre-fetch fallback, and it is deliberately the same value the file used to hard-code
// so that first paint, SIM, and every test that never calls applyScopeConfig behave exactly as
// they did before this became server-driven.
//
// Why it moved: the backend gates on the `scan_scope` SETTING, and this file used to declare
// `const ACTIVE_SCOPE_PRESET = 'engagement-14'` compiled into the bundle. Change the setting and the
// server's gate moved while every denominator, "N of 20 in scope" line and out-of-scope note in
// the UI went on describing the preset in the build. Two sources of truth for one question, and
// the wrong one was the one the customer could see. Same shape as the /ai/status split, where a
// stored override made the status page describe a model the worker was not using.
export let ACTIVE_SCOPE_PRESET = 'engagement-14'

// Customer-neutral wording for the UI. "Agreed scope" is the honest description: it is a
// checklist someone signed off, not a capability claim and not a WCAG subset.
export const SCOPE_LABEL = 'agreed scope'

// The criteria in force, and the per-format gate that mirrors the backend's `in_scope()`.
// `let`, not `const`: ES imports are live bindings, so reassigning these in applyScopeConfig()
// updates every consumer's next read. Components read them during render, so a re-render after
// apply is all that is needed — App.jsx triggers one.
export let SCOPE_SCS = scopeCriteria(ACTIVE_SCOPE_PRESET)
export let SCOPE_SIZE = SCOPE_SCS.size
let _fmtGate = (sc, fmt) => presetInScope(ACTIVE_SCOPE_PRESET, sc, fmt)
export const inScopeFmt = (sc, fmt) => _fmtGate(sc, fmt)

// The wider list the scope is carved out of, and the criteria the narrowing drops. Kept as a
// derived difference rather than a second literal so "N of the 20 are out of scope" cannot stop
// being arithmetically true.
export const CORE_SCS = DOCUMENTS_20
export let OUT_OF_SCOPE_SCS = new Set([...DOCUMENTS_20].filter((sc) => !SCOPE_SCS.has(sc)))

// A scope that is not a subset of the document core would make every "of the 20" sentence in the
// UI false, and the difference above would silently under-report. Asserted at module load AND
// re-asserted on every apply — a server-driven scope can now introduce this at runtime, which a
// load-time-only check would never see.
export let SCOPE_IS_SUBSET_OF_CORE = [...SCOPE_SCS].every((sc) => DOCUMENTS_20.has(sc))

// Adopt the scope the SERVER reports, from GET /config's `scope` field:
//   {name: "engagement-14", criteria: {"1.1.1": ["docx", …], …}}   a narrowing is in force
//   {name: "",           criteria: null}                        no restriction
//
// Returns true when anything changed, so the caller knows whether a re-render is warranted.
// Tolerates a missing/!malformed field by leaving the fallback in place: a config we cannot read
// must not silently collapse the UI's scope to nothing, which would read as "we assessed almost
// none of it" — the most alarming possible way to fail.
//
// `criteria: null` means NO narrowing, so the scope becomes the whole document core. It must not
// be treated as an empty scope; those are opposite meanings and one of them is a scary lie.
export function applyScopeConfig(cfg) {
  const scope = cfg && cfg.scope
  if (!scope || typeof scope !== 'object') return false
  const before = [...SCOPE_SCS].sort().join(',') + '|' + ACTIVE_SCOPE_PRESET

  if (scope.criteria == null) {
    ACTIVE_SCOPE_PRESET = scope.name || ''
    SCOPE_SCS = new Set(DOCUMENTS_20)
    _fmtGate = () => true                       // no narrowing: every (criterion, format) is in
  } else if (typeof scope.criteria === 'object' && Object.keys(scope.criteria).length) {
    const map = scope.criteria
    ACTIVE_SCOPE_PRESET = scope.name || ''
    SCOPE_SCS = new Set(Object.keys(map))
    // Mirrors the backend's in_scope(): an unknown format is never excluded, because the gate's
    // job is to honour a deliberate choice rather than invent one from a name it cannot parse.
    _fmtGate = (sc, fmt) => {
      const fmts = map[sc]
      if (!fmts) return false
      return fmt == null ? true : fmts.includes(fmt)
    }
  } else {
    return false                                 // present but empty/malformed — keep the fallback
  }

  SCOPE_SIZE = SCOPE_SCS.size
  OUT_OF_SCOPE_SCS = new Set([...DOCUMENTS_20].filter((sc) => !SCOPE_SCS.has(sc)))
  SCOPE_IS_SUBSET_OF_CORE = [...SCOPE_SCS].every((sc) => DOCUMENTS_20.has(sc))
  // DENOMINATOR is mutated IN PLACE, never reassigned: consumers import the object itself, so a
  // fresh object would leave them holding the old totals with no error to notice.
  DENOMINATOR.scope.total = SCOPE_SIZE
  DENOMINATOR.scope.question =
    `what did we agree to assess? — the ${SCOPE_SIZE} criteria in this engagement's ${SCOPE_LABEL}`
  return before !== ([...SCOPE_SCS].sort().join(',') + '|' + ACTIVE_SCOPE_PRESET)
}

// Which denominator a surface is using, as displayable text. Passed to a title/label rather
// than hard-coded at each call site so the three can never be described inconsistently.
// `noun` carries no number, so a caller renders "<count> of <total> <noun>" without two
// versions of the same figure ending up in one sentence.
export const DENOMINATOR = {
  traced: {
    key: 'traced',
    total: null,                                  // per-file; counted from stored traces
    noun: 'criteria traced for this document',
    question: 'did ACP look? — the criteria ACP recorded an outcome for on this file format',
  },
  core: {
    key: 'core',
    total: DOCUMENTS_20.size,
    noun: 'document-core criteria',
    question: `what does ACP certify? — the ${DOCUMENTS_20.size} document-applicable A/AA criteria`,
  },
  scope: {
    key: 'scope',
    total: SCOPE_SIZE,
    noun: `criteria in the ${SCOPE_LABEL}`,
    question: `what did we agree to assess? — the ${SCOPE_SIZE} criteria in this engagement's ${SCOPE_LABEL}`,
  },
}

// One sentence explaining what a narrowed view is leaving out, and why. Never rendered
// conditionally on the count being flattering: a criterion that vanishes without an account of
// itself is the trust problem, not the number it would have shown.
export const outOfScopeNote = (findings = 0) =>
  `${OUT_OF_SCOPE_SCS.size} of the ${DOCUMENTS_20.size} document-core criteria `
  + `(${[...OUT_OF_SCOPE_SCS].sort().join(', ')}) are outside this engagement’s ${SCOPE_LABEL} `
  + `and are not counted above`
  + (findings > 0 ? `, including ${findings} recorded finding${findings === 1 ? '' : 's'}` : '')
  + '.'

// The criteria a view should render: the agreed scope by default, the whole document core when
// the reader has asked to see everything.
export const criteriaFor = (showAll) => (showAll ? CORE_SCS : SCOPE_SCS)

export const PRESET_NAMES = Object.keys(SCOPE_PRESETS)
