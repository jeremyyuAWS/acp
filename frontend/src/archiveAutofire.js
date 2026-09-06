// The words the archive auto-fire screens are allowed to use, and the pure logic behind them.
//
// WHY THIS IS A SEPARATE MODULE, for the same reason lifecycleRules.js is: the wording IS the
// safety mechanism on these screens, and a sentence asserted in a DOM test is asserted through
// three layers of rendering. Here it can be asserted directly.
//
// THE VOCABULARY RULE, and it is the inverse of lifecycleRules.js's. That module forbids saying a
// file WAS archived, because a lifecycle rule only ever writes a recommendation. This lane really
// does move files — so the danger reverses: the words here must not say a file was archived when
// ACP does not KNOW that it was. Five states, five distinct sentences, and the two that must never
// blur into each other are:
//
//   · "Automatically archived" — the move happened AND was verified at the destination.
//   · "Recovery required"      — the move may or may not have happened, and nobody has checked.
//
// A provider that times out mid-move produces the second. Rendering it as the first would be the
// single most damaging thing this UI could do: it tells a records manager a document is safely in
// the archive when it may be in neither place, and it does so in the surface they would use to
// check.
//
// AND NOTHING HERE MAY SUGGEST AGE IS THE TRIGGER. Every screen that offers auto-fire states the
// opposite in plain words, at the point the choice is made — see `AGE_WARNING`, which the rule
// editor renders next to the toggle rather than in a footnote.

export const RECOMMEND_ONLY = 'recommend_only'
export const ELIGIBLE_AUTO = 'eligible_auto'
export const BLOCKED = 'blocked'
export const ARCHIVED = 'archived'
export const RECOVERY_REQUIRED = 'recovery_required'

/**
 * How each state is named, and how it is distinguished WITHOUT COLOR.
 *
 * `mark` is a text prefix, not an icon font or a colored dot: every state is legible in a
 * screenshot, in high contrast, in a terminal-rendered copy of the page, and to a reader who does
 * not perceive the color difference. WCAG 1.4.1 is the rule; the practical version is that this
 * is a page about irreversible actions and "the red one" is not a distinction anybody should have
 * to rely on.
 */
export const STATES = {
  [RECOMMEND_ONLY]: {
    mark: '—', label: 'Recommended for archive',
    help: 'A person decides. No evidence shows this document has been replaced, so it is never '
        + 'moved automatically.',
  },
  [ELIGIBLE_AUTO]: {
    mark: '›', label: 'Eligible for automatic archive',
    help: 'Evidence shows a newer document supersedes this one. Safety checks run again '
        + 'immediately before anything moves.',
  },
  [BLOCKED]: {
    mark: '!', label: 'Auto-archive blocked',
    help: 'A safety check refused this. The reason is shown with it; nothing was moved.',
  },
  [ARCHIVED]: {
    mark: '✓', label: 'Automatically archived',
    help: 'Moved to the archive destination and verified there afterwards.',
  },
  [RECOVERY_REQUIRED]: {
    mark: '?', label: 'Recovery required',
    help: 'The move could not be confirmed, so it is not known whether this document moved. '
        + 'It is not retried automatically — someone needs to look.',
  },
}

export const stateSpec = (state) => STATES[state] || {
  // An unrecognised state is reported as unrecognised. Falling back to a friendly-sounding label
  // would let a future backend state render as something reassuring by accident.
  mark: '?', label: 'State not recognised',
  help: 'ACP received a state it does not know how to describe. Treat it as unresolved.',
}

/** The state, as one string that reads correctly with no styling at all. */
export const stateText = (state) => `${stateSpec(state).mark} ${stateSpec(state).label}`

/** Which states mean a file was, or may have been, touched — the ones a reader must not skim. */
export const TOUCHED = new Set([ARCHIVED, RECOVERY_REQUIRED])

export const AGE_WARNING =
  'Age never triggers a move. A file is archived automatically only when ACP can show that a '
  + 'specific newer document replaces it — a “last modified before” condition on its own will '
  + 'always produce a recommendation for you to review.'

export const EVIDENCE_LABELS = {
  metadata_link: 'Replacement metadata names this document (retentionOf / supersedes)',
  rule_family: 'A lifecycle rule identifies a document family and a strictly newer version',
  sp_version: 'SharePoint version metadata names a newer approved replacement',
  admin_mapping: 'An administrator confirmed this document-family mapping',
}

export const evidenceLabel = (type) => EVIDENCE_LABELS[type] || String(type || 'Unrecognised evidence')

/**
 * A run's progress line, from MEASURED counts only.
 *
 * Mirrors archive_autofire.run_progress server-side, and carries the same refusal: no percentage
 * and no estimate. Eligibility is re-decided per item against the live tenant, so a percentage
 * would be a claim about a denominator that can still change — and this surface's entire job is
 * to be truthful about what has actually happened.
 */
export function runProgress(counts = {}) {
  const eligible = Number(counts.eligible || 0)
  const completed = Number(counts.completed || 0)
  const blocked = Number(counts.blocked || 0)
  const remaining = Math.max(0, eligible - completed - blocked)
  return `${eligible} eligible · ${completed} completed · ${blocked} blocked · ${remaining} remaining`
}

/**
 * The live-activity announcement for a screen reader, or '' when there is nothing worth saying.
 *
 * Returns '' for a repeated state so a polite live region is not re-announced on every poll —
 * the accessibility requirement is that MEANINGFUL transitions are announced, and "still
 * processing the same file" is not one. Timer ticks and decorative animation are never announced
 * because nothing here produces a message for them.
 */
export function transitionMessage(previous, next) {
  if (!next || !next.state) return ''
  if (previous && previous.state === next.state && previous.file === next.file) return ''
  const name = next.file || next.source_path || 'a document'
  if (next.state === ARCHIVED) return `${name} archived and verified.`
  if (next.state === RECOVERY_REQUIRED) return `${name} needs recovery — the move was not confirmed.`
  if (next.state === BLOCKED) return `${name} blocked: ${next.reason || 'a safety check refused it'}.`
  if (next.state === ELIGIBLE_AUTO) return `Processing ${name}.`
  return ''
}

/**
 * Why this policy cannot be turned on yet, or '' when it can.
 *
 * The client copy of api/archive_autofire.policy_problem, and only ever used to decide what to
 * OFFER — the server refuses regardless of what this says, so getting it wrong here costs a
 * misleading button, never an ungated activation. Same relationship DispositionRules.jsx's
 * FILE_CHANGING set has to disposition.SOURCE_MUTATING.
 */
export function policyProblem(policy) {
  const p = policy || {}
  if (!p.enabled) return ''
  if (!String(p.archive_root || '').trim()) {
    return 'Choose where archived files should go — automatic archival has nowhere to move them to.'
  }
  if (!(p.source_connections || []).length) return 'Choose at least one source connection this may act on.'
  if (!(p.rule_ids || []).length) return 'Choose at least one lifecycle rule whose candidates may be archived automatically.'
  if (!(p.required_evidence || []).length) return 'Require at least one type of supersession evidence.'
  if (Number(p.max_actions_per_run) < 1 || Number(p.max_actions_per_day) < 1) {
    return 'Set the per-run and per-day action ceilings to at least one.'
  }
  if (Number(p.max_actions_per_run) > Number(p.max_actions_per_day)) {
    return 'The per-run ceiling cannot exceed the per-day ceiling.'
  }
  return ''
}

/**
 * The summary a rule editor shows once the option is switched on: exactly what will happen.
 *
 * Returned as labelled rows rather than a paragraph because these are the four facts the PRD
 * requires be visible at the point of the decision — evidence, destination, daily ceiling,
 * dry-run status — and a reader scanning for one of them should not have to parse prose.
 */
export function policySummary(policy) {
  const p = policy || {}
  const evidence = (p.required_evidence || []).map(evidenceLabel)
  return [
    { label: 'Evidence required',
      value: evidence.length ? evidence.join('; ') : 'None chosen — nothing will be archived automatically.' },
    { label: 'Destination',
      value: p.archive_root
        ? `${p.archive_root}${p.preserve_hierarchy ? ' — original folder structure preserved beneath it'
                                                   : ' — all files placed directly in this folder'}`
        : 'Not set' },
    { label: 'Daily ceiling',
      value: `${Number(p.max_actions_per_day || 0).toLocaleString()} files a day, `
           + `${Number(p.max_actions_per_run || 0).toLocaleString()} per run` },
    { label: 'Dry run',
      value: p.dry_run
        ? 'On — every check runs against the real source and nothing is moved.'
        : 'Off — eligible files will be moved.' },
    { label: 'Minimum replacement age',
      value: `${Number(p.min_replacement_age_days || 0).toLocaleString()} days before the older `
           + 'version may be archived' },
  ]
}

/** Is the kill switch on? Stated as its own helper so the banner and the toggle cannot disagree. */
export const killSwitchOn = (policy) => !!(policy && policy.kill_switch)

/**
 * Turn a refused policy write into something a person can act on.
 *
 * The same shape lifecycleRules.refusalText has, and for the same reason: writing this policy is
 * admin-gated and running it is owner-gated, so a non-admin gets a 403 whose body says little. A
 * raw 403 reads as a bug rather than a permission, and a policy that silently failed to save is
 * indistinguishable from one that exists.
 */
export function refusalText(err) {
  const raw = String((err && err.message) || err || '').trim()
  if (/\b(403|forbidden|admin|owner|not authori[sz]ed|permission)\b/i.test(raw)) {
    return `Only a platform admin can change this, and only the account owner can start a run, so `
         + `nothing was changed. (${raw || 'refused by the server'})`
  }
  return raw || 'The server refused the change.'
}
