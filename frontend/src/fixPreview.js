// R4 — the decision layer over a single proposed fix.
//
// The repo already renders before/after four different ways, and this module deliberately adds a
// FIFTH of nothing. It answers the question the four renderers do not: *what does approving this
// actually do?* — which mode of fix this is, whether the "after" value is real yet, and where the
// bytes land. `GroundedBeforeAfter.jsx` stays the picture; this is the sentence beside it.
//
// Which of the four is the substrate, and why (read them; they are not interchangeable):
//   • GroundedBeforeAfter.jsx  — works from a remediation-inbox FINDING's own before/after fields,
//     via remediationEvidence.js. Every value it prints is the finding's own. **This is the one.**
//   • RemediationPreview.jsx   — the three-pane workspace's preview PANE. Wraps GroundedBeforeAfter
//     and adds page renders, zoom and mode switching. A pane, not a decision surface.
//   • BeforeAfterEvidence.jsx + beforeAfter.js — a different input entirely: an EvidenceCard `card`
//     prop, parsed out of a detail STRING. Correct where it is used; it cannot read a finding.
//   • BeforeAfter.jsx          — the upload flow. Its `baFor()` returns hand-written illustrative
//     markup per criterion ("3.1 : 1 · fails AA", a "West / 38%" table) that belongs to no document.
//     Nothing on the remediation path may build on it.
//
// HONESTY (ADR 0016): nothing here invents an "after". A fix whose value is computed at apply time
// says so; it never shows a placeholder that reads like a proposal. Data that has not loaded is
// reported as absent, never as a measured zero or a reassuring default.

import { laneOf, issueLabel, locationLabel, normSc } from './remediationInboxModel.js'
import { remediationTrack } from './remediationTrack.js'
import { findingSc, changeSentence } from './remediationEvidence.js'
import { hasGuidance, fixSteps } from './remediationGuide.js'
import { modeFor, fmtOf } from './capability.js'
import { WCAG } from './wcagCatalog.js'

// ── The four modes the redesign requires be shown explicitly, plus the one the code has and the
// board does not: a blocked finding is not a fix awaiting a decision, and must not be dressed as one.
export const FIX_MODES = {
  automatic: {
    key: 'automatic', label: 'Automatic fix available', tone: 'auto',
    help: 'ACP writes this one itself. Nothing is applied until you ask for it.',
  },
  'ai-draft': {
    key: 'ai-draft', label: 'AI draft — review wording', tone: 'draft',
    help: 'The wording below was generated. It is applied only if you approve it.',
  },
  guided: {
    key: 'guided', label: 'Guided fix', tone: 'guided',
    help: 'ACP cannot write this one. The steps for the source application are below.',
  },
  human: {
    key: 'human', label: 'Human authoring required', tone: 'human',
    help: 'There is no trustworthy draft for this. Someone has to write it.',
  },
  blocked: {
    key: 'blocked', label: 'Cannot be fixed here', tone: 'blocked',
    help: 'This finding is blocked — it cannot be remediated as it stands.',
  },
}

/** The criterion a finding names, from any field spelling the pipeline uses. `findingSc` reads
 *  rule_id/ruleId/wcag; queue rows built by the inbox also carry a bare `sc`. '' when unnamed. */
export const scOfFinding = (f) => findingSc(f) || normSc(f?.sc) || ''

const BY_SC = new Map(WCAG.map((c) => [c.sc, c]))

/** { sc, name, requirement } from the maintained catalog — name/requirement null for an unlisted
 *  criterion, so the caller omits the line rather than printing a guess. */
export function criterionOf(sc) {
  const e = BY_SC.get(sc)
  return { sc: sc || null, name: e?.name || null, requirement: e?.req || null }
}

/** Which mode of fix this finding is, and — the part that makes it checkable — WHAT decided that.
 *  Read from the finding's own real state first (its lane, which is driven by status and by whether
 *  a value is actually present), and only then from the criterion tables. `cap` is the capability
 *  map; omit it and the lane/track answer stands rather than a fabricated capability claim. */
export function fixModeOf(finding, { cap = null, fmt = null } = {}) {
  const lane = laneOf(finding)
  const sc = scOfFinding(finding)
  if (lane.key === 'blocked') return { ...FIX_MODES.blocked, basis: 'the finding is blocked' }
  // A rejected AI fix is not an AI draft any more — it was declined and handed to a person.
  if (lane.key === 'handoff') return { ...FIX_MODES.human, basis: 'the drafted fix was rejected and handed back' }
  if (lane.key === 'review') return { ...FIX_MODES.automatic, basis: 'ACP wrote this fix deterministically' }
  if (lane.key === 'apply') return { ...FIX_MODES['ai-draft'], basis: 'the finding carries a drafted value' }
  // manual / recheck: no value on the finding, so the mode is a fact about the criterion.
  // remediationTrack's human set wins over the capability table on purpose — the table marks some
  // genuinely-human criteria "auto" because a detector can DETECT them, and detecting is not fixing.
  if (remediationTrack({ sc }).track === 'human') {
    return { ...FIX_MODES.human, basis: sc ? `${sc} needs human judgement` : 'the criterion needs human judgement' }
  }
  if (cap && fmt && modeFor(cap, fmt, sc) === 'auto') {
    return { ...FIX_MODES.automatic, basis: `the capability table lists ${sc} on ${String(fmt).toUpperCase()} as automatic` }
  }
  if (hasGuidance(sc)) return { ...FIX_MODES.guided, basis: `${sc} has per-application fix steps` }
  return { ...FIX_MODES.human, basis: 'no drafted value and no criterion-specific steps' }
}

/** The value the fix would write. `known:false` means exactly that — not yet computed — and the
 *  caller must say so rather than render an empty box that reads like "no change". */
export function proposedValue(finding) {
  const v = finding?.after ?? finding?.proposals?.[0]?.proposed_value ?? null
  const known = v != null && String(v) !== ''
  return { value: known ? String(v) : null, known }
}

// Mirrors RemediationPreview.jsx's rule so the two surfaces cannot disagree about what "applied"
// means: a drafted `after` value is NOT applied — only real applied/approved state is.
const APPLIED_STATUSES = new Set(['applied', 'approved', 'accepted', 'verified'])

/** Did the fix genuinely land, and did the confirming re-scan clear it? */
export function appliedStateOf(finding) {
  const st = String(finding?.status || '').toLowerCase()
  return {
    applied: !!(finding?.applied || finding?.autoApplied || APPLIED_STATUSES.has(st)),
    verified: st === 'verified',
  }
}

/** Where the corrected bytes go — the sentence this product has got wrong before.
 *
 *  ADR 0010, verified in the tree rather than remembered: `store.get_drive_mirror_enabled()` reads
 *  `get_setting("drive_mirror_enabled", "true") != "false"`, so it defaults **TRUE**. With it on,
 *  `handlers.py` uploads the corrected copy to Blob *and* mirrors it into the drive's mirror folder
 *  (`drive_mirror_folder`, default "Remediated"). So "nothing is written to your drive" is false on
 *  a default deployment and must never be printed.
 *
 *  `driveMirror` is `{ enabled, folder }` from GET /settings, or **null when it has not been read**.
 *  Unread is not "off": it returns `known:false` and the caller says nothing about the destination.
 *  What is unconditional — a copy is produced, the original is untouched — is stated either way.
 *
 *  The mirror sentence is scoped to drive-sourced documents on purpose: `_remediate_file` requires a
 *  `drive_file_id` and a Drive token (handlers.py), so the setting being on does not by itself mean
 *  THIS document gets mirrored. PR #558's `deliveryPolicy.js` is the fuller treatment of the same
 *  ground truth and should replace this block once it lands — see the PR body. */
export function destinationOf(driveMirror = null) {
  const always = 'Applying the fix writes a corrected copy. The original document is not modified.'
  if (!driveMirror || driveMirror.enabled == null) return { known: false, always, drive: null }
  if (driveMirror.enabled) {
    const where = driveMirror.folder ? `the “${driveMirror.folder}” folder` : 'the mirror folder'
    return {
      known: true, always,
      drive: `For a document taken from the connected drive, a copy is also written to ${where} there.`,
    }
  }
  return { known: true, always, drive: 'The copy stays in ACP’s own storage; the source drive is not written to.' }
}

/** Everything the R4 surface renders, assembled from real finding fields. null for no finding —
 *  which the caller renders as an empty state, never as a blank fix card. */
export function fixPreviewModel(finding, { cap = null, fmt = null, driveMirror = null } = {}) {
  if (!finding) return null
  const resolvedFmt = fmt || fmtOf(finding)
  const sc = scOfFinding(finding)
  const mode = fixModeOf(finding, { cap, fmt: resolvedFmt })
  // Steps only where they are real: fixSteps falls back to the app's generic Accessibility Checker
  // path, which needs a known format to name the right app. Unknown format → no steps, not Word's.
  const needsSteps = mode.key === 'guided' || mode.key === 'human'
  const steps = needsSteps && resolvedFmt
    ? { ...fixSteps(sc, resolvedFmt), specific: hasGuidance(sc) }
    : null
  return {
    sc,
    criterion: criterionOf(sc),
    issue: issueLabel(finding),
    location: locationLabel(finding) || null,
    severity: finding?.severity || null,
    file: finding?.file || null,
    format: resolvedFmt,
    mode,
    proposed: proposedValue(finding),
    change: changeSentence(finding),
    ...appliedStateOf(finding),
    destination: destinationOf(driveMirror),
    steps,
  }
}
