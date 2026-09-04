import { assessMetrics, reconcile, coverageSentence, SEVERITIES, SEVERITY_LABEL,
         STATUS_LABEL } from './assessMetrics.js'

// The assessment summary: a status a person can check, then seven metrics, then the arithmetic.
//
// It replaces four panels that each led with a count of "problems" over an unstated denominator —
// the assess tile (112 findings), assessment coverage (13 needing remediation), assessment
// confidence (189 unresolved, which is 176 + 13 restated) and the capability scorecard (5/20, a
// property of ACP that does not change when you run anything). Two of them were called "Coverage"
// and answered different questions; two carried a primary button.
//
// THREE FACTS INSTEAD OF A SCORE. The accessibility score is deliberately absent. It has no
// documented weighting, and a single number lets three critical findings average away behind forty
// passes — it invites an argument about the number instead of work on the documents. What is here
// instead is status, coverage and findings: three statements a reviewer can check against the file
// list below them.
//
// AND THE COVERAGE SENTENCE NEVER TRAVELS ALONE. Where any selected check could not run, it sits
// beside the status — including, especially, when the status is "No findings". This screen gets
// screenshotted, and a bare "no findings" over a run that evaluated 14 of 17 criteria is the most
// damaging thing this product could print.

const TONE = {
  attention: { c: '#8a5a00', bar: '#B07A00' },
  partial: { c: '#8a5a00', bar: '#B07A00' },
  failed: { c: '#B3261E', bar: '#B3261E' },
  awaiting_review: { c: '#8a5a00', bar: '#B07A00' },
  clear: { c: '#2F7D32', bar: '#2F7D32' },
  empty: { c: 'var(--muted)', bar: '#9A93A0' },
}
const SEV_COLOR = { CRITICAL: '#8E1B14', SERIOUS: '#B3261E', MODERATE: '#B07A00', MINOR: '#B9B3BE' }

const card = {
  border: '1px solid var(--line)', borderRadius: 12, padding: '12px 14px', background: 'var(--surface)',
}
const lab = { fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.35 }
const val = { fontSize: 26, fontWeight: 700, fontVariantNumeric: 'tabular-nums', marginTop: 5, lineHeight: 1 }
const sub = { fontSize: 11.5, color: 'var(--muted)', marginTop: 5, lineHeight: 1.45 }

function Metric({ label, value, unit, children, tone }) {
  return (
    <div style={card}>
      <div style={lab}>{label}</div>
      {value !== undefined && (
        <div style={{ ...val, color: tone }}>
          {value}
          {unit && <span style={{ fontSize: 15, fontWeight: 400, color: 'var(--muted)' }}> {unit}</span>}
        </div>
      )}
      <div style={sub}>{children}</div>
    </div>
  )
}

// Board 7, state 6 — the run reached no terminal check. No metric renders, not even zero: a grid of
// zeros reads as "assessed, found nothing", and the whole point of this state is that nothing was
// assessed. The previous run's results stay reachable under their own timestamp (Run details).
function FailedState({ assessedAt, onReconnect, onRunDetails }) {
  return (
    <section className="panel assesssummary assesssummary-failed" role="status"
             style={{ borderLeft: `4px solid ${TONE.failed.bar}` }}>
      <div style={{ fontSize: 19, fontWeight: 650, color: TONE.failed.c }}>
        {STATUS_LABEL.failed}
      </div>
      <p className="muted" style={{ fontSize: 13.5, margin: '8px 0 0', lineHeight: 1.6, maxWidth: 640 }}>
        No document reached a verdict in this run{assessedAt ? ` (${assessedAt})` : ''}. Nothing was
        assessed and nothing was changed — this is not a run that found no problems, it is a run that
        did not happen.
      </p>
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        {onReconnect && <button type="button" onClick={() => onReconnect()}>Reconnect and retry</button>}
        {onRunDetails && (
          <button className="ghost small" type="button" onClick={() => onRunDetails()}>Run details</button>
        )}
      </div>
    </section>
  )
}

// Board 7, state 7 — the scope selected no assessable document. It states the CAUSE and offers the
// control that fixes it, and it never renders the summary grid with zeros: nothing was checked here,
// so nothing is clear. Distinct from state 6, where documents were selected but none could be read.
function EmptyState({ discovered, onChangeScope }) {
  return (
    <section className="panel assesssummary assesssummary-empty" role="status"
             style={{ borderLeft: `4px solid ${TONE.empty.bar}` }}>
      <div style={{ fontSize: 19, fontWeight: 650, color: TONE.empty.c }}>{STATUS_LABEL.empty}</div>
      <p className="muted" style={{ fontSize: 13.5, margin: '8px 0 0', lineHeight: 1.6, maxWidth: 640 }}>
        {discovered
          ? `Discovery listed ${discovered.toLocaleString()} files, and none is a .docx, .pdf, .pptx or .xlsx in the selected folders. `
          : 'No document in the selected scope is a format ACP can assess. '}
        Widening the document types or the folders will change that.
      </p>
      {onChangeScope && (
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button type="button" onClick={() => onChangeScope('types')}>Change document types</button>
          <button className="ghost small" type="button" onClick={() => onChangeScope('folders')}>Change folders</button>
        </div>
      )}
    </section>
  )
}

/**
 * @param files       the scan's file rows
 * @param cap         remediation-capability map
 * @param assessment  assessment-lane map
 * @param criteria    the agreed criteria (defaults to the agreed scope inside assessMetrics)
 * @param level       conformance target
 * @param notStarted  selected documents never begun — omit when unknown, see assessMetrics
 * @param onRemediate primary action
 * @param onRunDetails secondary — traces and capability live behind this, not on this screen
 */
export default function AssessSummary({ files, cap, assessment, criteria, level = 'AA',
                                        assessedAt, notStarted, run, discovered, integrityCaveat = null,
                                        onRemediate, onRunDetails, onReconnect, onChangeScope }) {
  // The run's own status decides two of the seven screen states the file list cannot: a run of
  // 'error' is `failed` even with a stray record, and one 'cancelled'/'interrupted' is `partial`
  // even before the not-started count is known. 'done'/absent leaves classification to the findings.
  const runStatus = run?.status
  const m = assessMetrics(files, { cap, assessment, criteria, level, notStarted, runStatus })
  // Nothing, rather than zeros. A run that has not happened is not a run that found nothing.
  if (!m) return null

  // ── Board 7, states 6 and 7: the two the previous screen rendered as an ordinary completed
  //    result. Neither may show the metrics grid — a grid of zeros is the same false verdict as a
  //    completed run that found nothing, and an empty scope never checked anything to be "clear"
  //    about. Each states its CAUSE and offers the control that changes it, and nothing else. ──
  if (m.status === 'failed') {
    return <FailedState assessedAt={assessedAt} onReconnect={onReconnect} onRunDetails={onRunDetails} />
  }
  if (m.status === 'empty') {
    return <EmptyState discovered={discovered} onChangeScope={onChangeScope} />
  }

  const tone = TONE[m.status] || TONE.attention
  const r = reconcile(m)
  const gaps = m.unableToAssess > 0 || m.documentsUnopened.length > 0
  const lifecycleExcluded = run?.scope?.lifecycle_eligible_excluded ?? 0
  // The by-severity addends, printed as an equation so the partition is checkable on screen — the
  // same reason the worklist prints its per-row sum. UNKNOWN joins only when it is non-zero, and the
  // whole thing reconciles to Total findings (assessMetrics guarantees sevSum === totalFindings).
  const sevAddends = [...SEVERITIES.map((s) => m.bySeverity[s]),
                      ...(m.bySeverity.UNKNOWN > 0 ? [m.bySeverity.UNKNOWN] : [])]

  return (
    <section className="panel assesssummary" style={{ borderLeft: `4px solid ${tone.bar}` }}>

      {/* ── Board 7, state 4: a partial run must be impossible to mistake for a full one. Every
             number below is of the documents that were assessed, not of the scope that was selected,
             so the banner names that denominator ONCE, at the top, before any metric is read. The
             not-started documents are named when the caller knows them (they are not in the file
             list — get_scan returns only what ran — so `notStarted` arrives separately or not at
             all; absent, the banner still fixes the "reads as complete" failure with the count it
             has). ── */}
      {m.status === 'partial' && (
        <div className="assesssummary-partial" role="status"
             style={{ marginBottom: 14, padding: '11px 13px', borderRadius: 10,
                      border: `1px solid ${TONE.partial.bar}`, background: 'var(--surface)' }}>
          <div style={{ fontSize: 15, fontWeight: 650, color: TONE.partial.c }}>
            {STATUS_LABEL.partial} — {m.documentsAssessed} document{m.documentsAssessed === 1 ? '' : 's'} assessed
          </div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 4, lineHeight: 1.6 }}>
            The run stopped before its scope was complete. Every number below is <b>of the{' '}
            {m.documentsAssessed} assessed</b>
            {notStarted > 0 ? <>, and {notStarted} selected document{notStarted === 1 ? '' : 's'} {notStarted === 1 ? 'was' : 'were'} never started.</> : '.'}
          </div>
        </div>
      )}

      {/* ── A1 · what this run was, before its numbers. The level is stated, never chosen here, and
             the criteria count is the selected scope — the same denominator the coverage sentence
             reads against, so "17 selected criteria" and "14 of 17 evaluated" can never disagree.
             The timestamp arrives pre-formatted (or absent → no segment), exactly as AssessSetup's
             discovery stamp does, so this component formats no dates of its own. ── */}
      <div className="assesssummary-head" style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 17, fontWeight: 650 }}>Assessment results</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
          {assessedAt ? `${assessedAt} · ` : ''}WCAG 2.1 Level {level} · {m.coverageSelected} selected criteria
          {lifecycleExcluded > 0 && ` · ${lifecycleExcluded} excluded by lifecycle policy`}
        </div>
      </div>

      {/* ── Status: three checkable facts, no score ─────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 40, alignItems: 'center', flexWrap: 'wrap' }}>
          <div>
            <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                                            fontWeight: 600 }}>Assessment status</div>
            <div style={{ fontSize: 19, fontWeight: 650, color: tone.c, marginTop: 4 }}>
              {STATUS_LABEL[m.status]}
            </div>
            {/* RUN INTEGRITY TRAVELS WITH THE STATUS, and the reason is the same one the coverage
                sentence has: this is the line that gets read as the answer, and a status of
                "No findings" over a run that completed 17 of 34 checks is the most damaging thing
                this screen can print. `coverageSentence` above says how much of the SCOPE was
                evaluated; this says whether the run that evaluated it actually finished doing so.
                Two different failures, and the second was invisible until the Run integrity panel
                existed — the manifest recorded every un-run check as a pass. Null, and absent,
                only when the run is genuinely complete (runIntegrity.js: integrityCaveat). */}
            {integrityCaveat && (
              <div role="status" style={{ fontSize: 12.5, marginTop: 5, color: TONE.attention.c,
                                          fontWeight: 600, maxWidth: 320 }}>
                {integrityCaveat}
              </div>
            )}
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                                            fontWeight: 600 }}>Coverage</div>
            <div style={{ fontSize: 15, marginTop: 5 }}>{coverageSentence(m)}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                                            fontWeight: 600 }}>Findings</div>
            <div style={{ fontSize: 15, marginTop: 5 }}>
              {m.totalFindings} across {m.documentsNeedingAttention} document{m.documentsNeedingAttention === 1 ? '' : 's'}
            </div>
          </div>
        </div>
        <span style={{ display: 'flex', gap: 8 }}>
          {onRunDetails && (
            <button className="ghost small" type="button" onClick={() => onRunDetails()}>Run details</button>
          )}
          {m.totalFindings > 0 && onRemediate && (
            <button type="button" onClick={() => onRemediate()}>Start remediation</button>
          )}
        </span>
      </div>

      {/* The caveat that stops a clean-looking run being circulated as a clean bill of health. */}
      {/* Gated on "found nothing", NOT on the `clear` status. A run where every completed check
          passed but a criterion is still awaiting a person reads as `awaiting_review` — and it is
          just as circulatable as a screenshot, so it needs the same caveat. Gating on the status
          name would have left that case bare. */}
      {gaps && m.totalFindings === 0 && (
        <p className="muted" style={{ fontSize: 12.5, margin: '10px 0 0', lineHeight: 1.6 }}>
          No findings is not the same as conformant — {m.unableToAssess} of {m.selectedChecks} selected
          checks could not run{m.documentsUnopened.length > 0
            ? `, and ${m.documentsUnopened.length} document${m.documentsUnopened.length === 1 ? '' : 's'} failed to open`
            : ''}.
        </p>
      )}

      {/* Board 7, state 5 — gaps named at the TOP, with the reason, not tucked below the numbers they
          invalidate. The no-findings case is already caveated just above; this covers the state-5-
          overlays-state-2 case the board calls out by name — a run that DID find things and ALSO
          could not assess part of the estate, where the gap otherwise sits only in the list at the
          very bottom, under every total it qualifies. */}
      {gaps && m.totalFindings > 0 && (
        <div className="assesssummary-gaps" role="status"
             style={{ marginTop: 12, padding: '10px 13px', borderRadius: 10,
                      border: '1px solid #B07A00', background: 'var(--surface)' }}>
          <div style={{ fontSize: 13.5, fontWeight: 650, color: '#8a5a00' }}>
            Part of this run could not be assessed
          </div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 3, lineHeight: 1.6 }}>
            {m.documentsUnopened.length > 0 && (
              <><b>{m.documentsUnopened.length}</b> document{m.documentsUnopened.length === 1 ? '' : 's'} could
                not be opened{m.unableToAssess > 0 ? '; ' : ' (named below). '}</>
            )}
            {m.unableToAssess > 0 && (
              <><b>{m.unableToAssess}</b> of {m.selectedChecks} selected checks could not run
                {m.unassessableCriteria.length > 0
                  ? ` — ${m.unassessableCriteria.length} criteria have no method for these formats`
                  : ''}. </>
            )}
            Coverage is {m.coverageEvaluated} of {m.coverageSelected} criteria, never a clean bill of
            health across the whole estate. These are not passes, not failures and not findings.
          </div>
        </div>
      )}

      {/* ── The seven, and only these seven ──────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                    gap: 12, marginTop: 16 }}>

        {/* Deva, 20 Aug: "we should NOT have any exclusions at this stage" — everything knowable
            from metadata (file type, lifecycle tag, folder) is excluded BEFORE the run, so the
            results screen should not present a second exclusion list.
            Half of that is already true and half of it cannot be: discovery is metadata-only
            (`handlers.py:148` — list, classify, STOP), so it never opens a file. Password
            protection, corruption and unsupported internal variants are only discoverable by
            trying to read the document, which happens here. So those files are not an exclusion,
            they are an OUTCOME of this run — and the "of 22" framing was what made them read as
            one. The count stands alone; the failures are reported below as failures. */}
        <Metric label="Documents assessed" value={m.documentsAssessed}>
          Files where at least one selected check completed.
        </Metric>

        <Metric label="Documents needing attention" value={m.documentsNeedingAttention}
                tone={m.documentsNeedingAttention ? '#B3261E' : undefined}>
          Files with at least one unresolved finding.
        </Metric>

        <Metric label="Total findings" value={m.totalFindings}>
          Individual instances, not criteria — one criterion can produce many.
        </Metric>

        <div style={card}>
          <div style={lab}>Findings by severity</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 9 }}>
            {SEVERITIES.map((s) => (
              <span key={s} style={{ fontSize: 11.5, fontVariantNumeric: 'tabular-nums',
                                     display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2,
                                                  background: SEV_COLOR[s], display: 'inline-block' }} />
                <b>{m.bySeverity[s]}</b> {SEVERITY_LABEL[s]}
              </span>
            ))}
            {/* Never dropped. An unrecognised severity that vanished would break the printed sum
                silently, which is worse than an odd label. */}
            {m.bySeverity.UNKNOWN > 0 && (
              <span style={{ fontSize: 11.5 }}><b>{m.bySeverity.UNKNOWN}</b> unclassified</span>
            )}
          </div>
          {/* A6 · the partition, added up on screen. A severity breakdown with no visible sum is a
              set of numbers a reader has to trust; printed as an equation it is one they can check
              against Total findings in the tile beside it. Only when there is something to add. */}
          {m.totalFindings > 0 && (
            <div className="muted assesssummary-sevsum" style={{ fontSize: 11, marginTop: 8,
                                                                 fontVariantNumeric: 'tabular-nums' }}>
              {sevAddends.join(' + ')} = {m.totalFindings}
            </div>
          )}
        </div>

        <Metric label="Auto-fix available" value={m.autoFixAvailable} tone="#2F7D32">
          Findings with a deterministic remediation. Excludes AI-drafted suggestions, which need
          approval and are counted under review.
        </Metric>

        <Metric label="Human review required" value={m.humanReviewRequired}>
          Findings needing a person’s judgement, including every AI-drafted fix awaiting approval.
        </Metric>

        <Metric label="Unable to assess" value={m.unableToAssess} unit="checks">
          Selected checks that could not run
          {m.unassessableCriteria.length > 0 && <> — {m.unassessableCriteria.length} criteria
            with no method for these formats</>}. Not passes and not failures.
        </Metric>

        {/* Board 4's 8th cell — the shape of the grid states what is NOT here as loudly as what is.
            A reader who has seen a compliance dashboard expects a score; its absence is a decision,
            and naming the decision on the screen is what stops "where's the percentage?" becoming a
            request to reinstate one. No value — this cell is an explanation, not a metric. */}
        <div style={{ ...card, background: 'transparent', borderStyle: 'dashed' }}>
          <div style={lab}>Deliberately absent</div>
          <div style={{ fontSize: 13, marginTop: 8, lineHeight: 1.5 }}>
            No accessibility score · no percentages · no time-per-person estimate.
          </div>
          <div style={sub}>
            A single score lets a critical failure average away behind passes, and cannot tell
            “checked and passed” from “not checked” — the one distinction this screen exists to make.
          </div>
        </div>
      </div>

      {/* ── The arithmetic, printed. Either it holds on screen or it is a visible bug. ───── */}
      <div className="muted" style={{ fontSize: 12, marginTop: 12, paddingTop: 10,
                                      borderTop: '1px solid var(--line)', lineHeight: 1.6 }}>
        <div>{r.findings.line}</div>
        <div>{r.checks.line}</div>
      </div>

      {/* ── Named, not dropped ───────────────────────────────────────────────────────────── */}
      {m.documentsUnopened.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
          <div style={{ fontSize: 13, fontWeight: 650 }}>
            {m.documentsUnopened.length} document{m.documentsUnopened.length === 1 ? '' : 's'} failed to open
            during this run
          </div>
          <ul className="muted" style={{ fontSize: 12.5, margin: '6px 0 0', paddingLeft: 18, lineHeight: 1.6 }}>
            {m.documentsUnopened.map((d) => (
              <li key={d.file}>
                <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{d.name}</span>
                {d.reason ? ` — ${d.reason}` : ''}
              </li>
            ))}
          </ul>
          <div className="muted" style={{ fontSize: 12, marginTop: 7 }}>
            {/* Not "excluded". Nothing excluded these — the scope selected them and the run could
                not read them, which is a result rather than a filter. Saying so is what keeps the
                assessed count honest without smuggling an exclusion list back onto the screen. */}
            These were selected for assessment and produced no verdict. They are not passes, not
            failures and not findings, and they hold no work until they can be opened.
          </div>
        </div>
      )}
    </section>
  )
}
