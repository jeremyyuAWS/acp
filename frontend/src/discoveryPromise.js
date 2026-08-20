// What discovery actually does, said before it runs.
//
// Two facts belong on the review step and were not there. Both are promises the product makes and
// neither was visible at the moment a user commits to a run.
//
// ── METADATA ONLY ─────────────────────────────────────────────────────────────────────────────
// `_defer_analysis_to_assess()` defaults on (ADR 0020): discovery lists the estate from metadata,
// opens no file, downloads nothing, and changes nothing at the source. That is the strongest claim
// this product makes about a customer's drive, and the easiest to quietly break — a future change
// that starts downloading during Discover would violate it silently, because nothing on screen
// asserts it. Stating it here makes the promise visible to the person authorising the run, and
// makes its removal a visible edit rather than an invisible regression.
//
// ── WHICH RULES WILL RUN ──────────────────────────────────────────────────────────────────────
// Lifecycle rules tag matching files during the run (DS-07: "persist the rule set with the
// discovery-run snapshot ... results can be traced to the exact rules used"). A user who cannot
// see the rule count at commit time cannot tell an unrulled run from a rulled one afterwards,
// because both produce an inventory. Naming the count is what makes the later tags attributable.
//
// NOTE ON WORDING, from the PRD: never say a file was archived or deleted when the system has only
// written a recommendation. These strings say "tag" and "recommendation" throughout, deliberately.

/** Lifecycle actions — the two that produce a recommendation tag. Mirrors DispositionRules. */
const LIFECYCLE = new Set(['archive', 'delete'])

export const METADATA_ONLY_TITLE = 'Metadata only — no file is opened'

export const METADATA_ONLY_BODY =
  'Discovery reads names, paths, sizes and dates. It does not download content, does not inspect '
  + 'documents for WCAG issues, and does not modify anything in the source. Content is read later, '
  + 'only for the files you choose to assess.'

/**
 * How many enabled lifecycle rules will run, and what that means.
 *
 * Returns `null` while the rule list is still loading — the caller renders nothing rather than
 * "0 rules", which would state that no file will be tagged before we know whether that is true.
 * Same distinction as `by_age` in #517: a missing answer is not a measured zero.
 */
export function lifecycleRuleSummary(policies) {
  if (!Array.isArray(policies)) return null
  const on = policies.filter((p) => p && p.enabled && LIFECYCLE.has(p.action))
  if (!on.length) {
    return { count: 0, line: 'None enabled', detail: 'No file will be tagged for archive or deletion review.' }
  }
  return {
    count: on.length,
    line: `${on.length} enabled`,
    // Says what a rule DOES, because "2 enabled" alone does not distinguish tagging from acting.
    detail: 'Matching files are tagged for review. Nothing is moved, trashed or changed.',
    names: on.map((p) => p.name).filter(Boolean),
  }
}
