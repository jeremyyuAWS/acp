// Can this run's results be presented as a conformance result — and if not, exactly why?
//
// The pure half of the Assessment Run Integrity Gate. It takes the scan manifest
// (GET /scans/{sid}/manifest) plus what the app knows about the run, and returns one verdict
// object. No DOM, no fetching: the verdict is the safety mechanism on this screen, so it has to
// be assertable directly rather than through a rendered tree.
//
// WHY A GATE EXISTS AT ALL. Until 2026-09-01 the manifest could not express incompleteness. Every
// rule that produced neither a finding nor an attributable error was recorded PASS, and the error
// list never reached it (Rubric.assess returns a COUNT and drops the list), so `rules_errored_total`
// was structurally 0 and `complete` structurally true. Measured: a .docx the engine could not open
// recorded 17 PASS, completeness 100%, complete: true. api/store.py's _save_file_manifest carries
// the full account. The backend now says NOT_CHECKED; this decides what may be claimed on the
// strength of what it says.
//
// THE FOUR STATUSES ARE NOT INTERCHANGEABLE, and collapsing any two of them is how the original
// defect happened:
//
//   passed          the rule ran and found nothing              — evidence of compliance
//   failed          the rule ran and found something            — evidence, and a completed check
//   notChecked      the rule applies and did not run            — ABSENCE of evidence
//   errored         the rule was attempted and the engine broke — absence of evidence, with a cause
//   notApplicable   the rule belongs to another format          — nothing was ever owed
//
// `passed` and `notChecked` look identical in any count that adds them together, which is precisely
// what "0 findings" does. So this module never produces a single "clean" number: a caller that wants
// to say something reassuring has to read `conformanceClaimAllowed` first.

/** Verdict kinds, in the order a caller should test them. */
export const COMPLETE = 'complete'
export const INCOMPLETE = 'incomplete'
export const UNAVAILABLE = 'unavailable'
export const STALE = 'stale'
export const PENDING = 'pending'

/** Per-rule statuses as the manifest spells them. */
export const PASS = 'PASS'
export const FAIL = 'FAIL'
export const ERROR = 'ERROR'
export const NOT_CHECKED = 'NOT_CHECKED'
export const NOT_APPLICABLE = 'NOT_APPLICABLE'

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)

/**
 * Why a file could not be fully assessed, in the reader's words.
 *
 * `reason` and `file_status` are the manifest's own machine tokens; nothing here invents a cause
 * the backend did not report. An unrecognised token falls through to a description of the SHAPE of
 * the gap rather than a guess at its cause — a wrong explanation is worse than none, because it
 * sends someone to fix the wrong thing.
 */
export function fileGapReason(file) {
  if (!file) return null
  if (file.reason === 'unsupported_format') return 'Not a format ACP assesses — no checks were owed.'
  if (file.reason === 'no_manifest') return 'No check results were recorded for this file at all.'
  if (file.file_status === 'error') return 'The engine could not analyse this file.'
  if (file.file_status === 'skipped') return 'Deliberately not analysed (ACP-generated copy of its own source).'
  if (num(file.rules_errored) > 0) return 'The engine failed on some checks.'
  if (num(file.rules_errored_unattributed) > 0) return 'Some checks errored; which ones was not recorded.'
  if (num(file.rules_not_checked) > 0) return 'Some applicable checks did not run.'
  return null
}

/**
 * The integrity verdict for one run.
 *
 * @param manifest  the GET /scans/{sid}/manifest payload, or null when it could not be read
 * @param opts.error        a fetch/read failure, if the manifest could not be loaded
 * @param opts.loading      the manifest read is in flight and nothing is known yet
 * @param opts.runInFlight  a NEW assessment is running right now, so anything on screen describes
 *                          the previous one
 * @param opts.manifestScanId / opts.currentScanId  which run the manifest describes vs. which run
 *                          the screen is showing — a mismatch is stale by identity, not by timing
 */
export function runIntegrity(manifest, opts = {}) {
  const { error = null, loading = false, runInFlight = false,
          manifestScanId = null, currentScanId = null } = opts

  // STALENESS IS CHECKED FIRST, and before `loading`, because it is the only state where the
  // numbers are internally consistent and still must not be believed. A manifest that describes
  // the previous run reads as a complete, passing, perfectly ordinary result — there is nothing
  // in the payload itself to notice. The two ways it happens are a new run in flight, and a
  // manifest whose scan_id is not the scan on screen; the second survives a reload, where a
  // "is something running" flag does not.
  const identityMismatch = Boolean(manifestScanId && currentScanId
                                   && manifestScanId !== currentScanId)
  if (runInFlight || identityMismatch) {
    return {
      status: STALE,
      conformanceClaimAllowed: false,
      // Deliberately no counts. Rendering last run's numbers under a "superseded" heading is how
      // a screenshot ends up quoting them as this run's.
      headline: 'These results describe an earlier run',
      detail: identityMismatch
        ? 'The coverage record on file is for a different run than the one shown.'
        : 'A new assessment is in progress. Coverage for it is not known until it finishes.',
      counts: null,
      files: [],
      manifestScanId: manifestScanId || null,
    }
  }

  if (loading) {
    return {
      status: PENDING, conformanceClaimAllowed: false,
      headline: 'Checking run coverage', detail: null, counts: null, files: [],
    }
  }

  // A manifest that could not be read is NOT a complete one. This is the same failure the boot
  // reads had (#1149/#1150): the absence of an answer defaulting to the reassuring one. An
  // unknown coverage record cannot license a conformance claim, so it does not.
  if (error || !manifest || typeof manifest !== 'object') {
    return {
      status: UNAVAILABLE, conformanceClaimAllowed: false,
      headline: 'Run coverage could not be read',
      detail: 'Without the coverage record these results cannot be presented as a conformance '
            + 'result. The findings below are still what this run recorded.',
      counts: null, files: [], readError: error ? String(error.message || error) : null,
    }
  }

  const expected = num(manifest.rules_expected_total)
  const errored = num(manifest.rules_errored_total)
  const notChecked = num(manifest.rules_not_checked_total)
  const unattributed = num(manifest.rules_errored_unattributed_total)
  const checked = num(manifest.rules_checked_total)
  const notApplicable = num(manifest.rules_not_applicable_total)

  const allFiles = Array.isArray(manifest.files) ? manifest.files : []
  // Files with a real gap. `unsupported_format` is excluded on purpose: nothing was owed for it,
  // so listing it as "affected" would send a reviewer looking for a fault that is not there.
  const affected = allFiles.filter((f) => f.reason !== 'unsupported_format'
    && (num(f.rules_errored) > 0 || num(f.rules_not_checked) > 0
        || num(f.rules_errored_unattributed) > 0 || f.complete === false))

  // Trust the backend's own `complete` where it gives one, but never upgrade a run to complete on
  // the strength of it: the counts have to agree. `complete` was structurally true for years, so a
  // reader that believed it alone would have believed that too.
  const missing = errored + notChecked + unattributed
  const complete = missing === 0 && affected.length === 0 && manifest.complete !== false

  const counts = {
    expected,
    checked,
    errored,
    notChecked,
    unattributed,
    notApplicable,
    missing,
    filesTotal: num(manifest.files_total),
    filesAffected: affected.length,
    // Recomputed here rather than taken from the payload, and asserted to agree with it — the
    // percentage is the number that gets screenshotted, so it should not be the one number this
    // module takes on trust.
    completenessPct: expected > 0 ? Math.round((checked / expected) * 100) : 100,
    reportedCompletenessPct: num(manifest.completeness_pct),
  }
  // Does the manifest's own arithmetic add up? Rendered, not just asserted, so a partition that
  // stops summing is visible to the reader rather than only to whoever reads the query.
  counts.reconciles = checked + errored + notChecked + unattributed === expected

  if (complete) {
    return {
      status: COMPLETE,
      conformanceClaimAllowed: true,
      headline: 'Every applicable check ran',
      detail: `${checked} of ${expected} applicable checks completed across `
            + `${counts.filesTotal} file${counts.filesTotal === 1 ? '' : 's'}.`,
      counts,
      files: [],
    }
  }

  return {
    status: INCOMPLETE,
    conformanceClaimAllowed: false,
    headline: 'Coverage is incomplete — these results are not a conformance result',
    detail: `${checked} of ${expected} applicable checks completed. `
          + `${missing} did not run, across ${affected.length} `
          + `file${affected.length === 1 ? '' : 's'}.`,
    counts,
    files: affected.map((f) => ({
      file: f.file,
      fileStatus: f.file_status || null,
      reason: f.reason || null,
      why: fileGapReason(f),
      expected: num(f.rules_expected),
      checked: num(f.rules_checked),
      errored: num(f.rules_errored),
      notChecked: num(f.rules_not_checked),
      unattributed: num(f.rules_errored_unattributed),
      completenessPct: num(f.completeness_pct),
    })),
  }
}

/**
 * The rules of one file that did not run, so the panel can name criteria rather than only count
 * them. Sorted by rule id for a stable read; NOT_APPLICABLE is never included — it is not a gap.
 */
export function skippedRulesOf(file) {
  const rules = Array.isArray(file?.rules) ? file.rules : []
  return rules
    .filter((r) => r.status === NOT_CHECKED || r.status === ERROR)
    .map((r) => ({ ruleId: r.rule_id, status: r.status }))
    .sort((a, b) => String(a.ruleId).localeCompare(String(b.ruleId)))
}

/**
 * One sentence a caller can put NEXT TO a headline result, whatever that result says.
 *
 * Returns null only when the run is genuinely complete. Everywhere else it returns something,
 * including — especially — when the findings are clean: a "no findings" over a run that evaluated
 * 48 of 68 checks is the single most damaging thing this product could print, and it is exactly
 * the case where nothing on screen looks wrong. AssessSummary already applies this discipline to
 * its own coverage sentence; this is the same rule applied to run execution.
 */
export function integrityCaveat(verdict) {
  if (!verdict || verdict.status === COMPLETE) return null
  if (verdict.status === STALE) return 'Superseded by a run in progress — not a result for this run.'
  if (verdict.status === PENDING) return 'Run coverage is still being checked.'
  if (verdict.status === UNAVAILABLE) return 'Run coverage is unknown — not a conformance result.'
  const c = verdict.counts
  return `${c.checked} of ${c.expected} applicable checks completed — not a conformance result.`
}
