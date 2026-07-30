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

// The preset in force for the SPA's default view. A name, deliberately — the customer's own
// name never reaches the UI (the label below is what a reader sees), and the backend gates on
// the same key via its `scan_scope` setting.
export const ACTIVE_SCOPE_PRESET = 'deva-final'

// Customer-neutral wording for the UI. "Agreed scope" is the honest description: it is a
// checklist someone signed off, not a capability claim and not a WCAG subset.
export const SCOPE_LABEL = 'agreed scope'

// The 14 criteria in force, and the per-format gate that mirrors the backend's `in_scope()`.
export const SCOPE_SCS = scopeCriteria(ACTIVE_SCOPE_PRESET)
export const SCOPE_SIZE = SCOPE_SCS.size
export const inScopeFmt = (sc, fmt) => presetInScope(ACTIVE_SCOPE_PRESET, sc, fmt)

// The wider list the scope is carved out of, and the criteria the narrowing drops. Kept as a
// derived difference rather than a second literal so "N of the 20 are out of scope" cannot stop
// being arithmetically true.
export const CORE_SCS = DOCUMENTS_20
export const OUT_OF_SCOPE_SCS = new Set([...DOCUMENTS_20].filter((sc) => !SCOPE_SCS.has(sc)))

// A scope that is not a subset of the document core would make every "of the 20" sentence in the
// UI false, and the difference above would silently under-report. Assert it at module load: the
// presets are generated from Python, so this catches a backend edit that widens a preset past
// what these surfaces claim to be narrowing. Pinned by activeScope.test.js.
export const SCOPE_IS_SUBSET_OF_CORE = [...SCOPE_SCS].every((sc) => DOCUMENTS_20.has(sc))

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
