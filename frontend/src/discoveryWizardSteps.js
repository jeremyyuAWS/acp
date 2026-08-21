// The three steps of "New discovery", as data rather than as markup.
//
// WHY THERE IS A STEPPER AGAIN. This wizard carried one, then lost it, and the note explaining
// the removal is still in ScanScopeWizard.jsx because the reasoning was right at the time:
//
//     No stepper. Discover asks ONE question — where should ACP inventory? — and a progress rail
//     across a single step is chrome implying choices that are no longer here.
//
// That was true when #532 stripped the format and criterion pickers out and left exactly one
// decision behind. It is not true now. Lifecycle rules are a real second decision — they run
// DURING discovery and tag matching files, and the rule set is frozen onto the run (DS-07) — and
// the review is a real third: it is the last screen before a run against somebody's estate, and
// the only place the metadata-only promise is made. A rail over three genuine steps is not chrome;
// it is the answer to "how much more of this is there", asked by someone looking at a folder tree
// for the first time.
//
// So the rail comes back for the REASON the note gave, not in spite of it: it tracks the number of
// real decisions, and that number changed.
//
// Kept out of the component because step order, labels and the forward/back rules are the parts
// worth asserting directly. A stepper whose "completed" ticks disagree with which step you can
// actually reach is a bug you only see by clicking, and clicking is what this repo cannot do (the
// preview server serves the shared checkout, not a branch).

import { blockedReason } from './wizardScopeReady.js'

/** In order. `id` is the step number the UI switches on; `title` is the rail label. */
export const WIZARD_STEPS = [
  { id: 1,
    title: 'Source and folders',
    subtitle: 'Choose where ACP should inventory. Every readable file in scope is listed.',
    // The forward label is DATA, not derived from the next step's title. "Continue to rules"
    // reads better than "Continue to lifecycle rules" and matches the approved board; deriving it
    // would mean a string-munging rule that produces one of them wrong.
    forward: 'Continue to rules →' },
  { id: 2,
    title: 'Lifecycle rules',
    subtitle: 'Rules run during discovery and tag matching files. Nothing is moved, trashed or changed.',
    forward: 'Continue to review →' },
  { id: 3,
    title: 'Review and run',
    subtitle: null,
    // Not "Continue": this one starts a run against somebody's estate, and the last control before
    // that should name the action rather than the navigation.
    forward: 'Run discovery →' },
]

export const FIRST_STEP = WIZARD_STEPS[0].id
export const LAST_STEP = WIZARD_STEPS[WIZARD_STEPS.length - 1].id

/** The step record, or null for a number that is not a step. */
export const stepInfo = (n) => WIZARD_STEPS.find((s) => s.id === n) || null

/**
 * Why the wizard may not leave `step` yet, or null when it may.
 *
 * ONLY step 1 can block, and only for the reason `wizardScopeReady` already owns: "Specific
 * folders" chosen with none selected. That case is not cosmetic — an empty folder list falls
 * through to the WHOLE source, so advancing from it authorises the opposite of what the mode says
 * (#502). Reused rather than re-derived so the rail and the footer cannot disagree about it.
 *
 * Steps 2 and 3 never block. A discovery with no lifecycle rules is a perfectly good discovery —
 * requiring one would invent a prerequisite the backend does not have.
 */
export function stepBlockedReason(step, scopeMode, folders) {
  return step === FIRST_STEP ? blockedReason(scopeMode, folders) : null
}

/** The next step, or null at the end. Null when the current step is blocked — the caller renders a
 *  disabled control carrying the reason rather than a control that silently does nothing. */
export function nextStep(step, scopeMode, folders) {
  if (stepBlockedReason(step, scopeMode, folders)) return null
  const i = WIZARD_STEPS.findIndex((s) => s.id === step)
  return i >= 0 && i < WIZARD_STEPS.length - 1 ? WIZARD_STEPS[i + 1].id : null
}

/** The previous step, or null at the start. Back is NEVER blocked: a user who cannot go back from
 *  a step they cannot complete forward is stuck on a modal. */
export function prevStep(step) {
  const i = WIZARD_STEPS.findIndex((s) => s.id === step)
  return i > 0 ? WIZARD_STEPS[i - 1].id : null
}

/** The forward control's label for a step. Falls back to a plain "Continue →" for a step number
 *  that is not one of ours, rather than rendering `undefined` into a button. */
export function forwardLabel(step) {
  return (stepInfo(step) || {}).forward || 'Continue →'
}

/**
 * The rail's state for every step, given where the user is.
 *
 * `done` is "you have been past this", not "this is valid" — the two differ and conflating them is
 * how a rail ends up ticking a step whose input is still incomplete. Forward movement is already
 * gated by `nextStep`, so anything behind the current step was passable when it was passed.
 */
export function railState(step) {
  return WIZARD_STEPS.map((s) => ({
    ...s,
    done: s.id < step,
    current: s.id === step,
    upcoming: s.id > step,
  }))
}
