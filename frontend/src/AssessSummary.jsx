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
  attention: { c: '#B07A00', bar: '#B07A00' },
  partial: { c: '#B07A00', bar: '#B07A00' },
  failed: { c: '#B3261E', bar: '#B3261E' },
  awaiting_review: { c: '#B07A00', bar: '#B07A00' },
  clear: { c: '#2F7D32', bar: '#2F7D32' },
  empty: { c: '#6c6470', bar: '#9A93A0' },
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
                                        notStarted, onRemediate, onRunDetails }) {
  const m = assessMetrics(files, { cap, assessment, criteria, level, notStarted })
  // Nothing, rather than zeros. A run that has not happened is not a run that found nothing.
  if (!m) return null

  const tone = TONE[m.status] || TONE.attention
  const r = reconcile(m)
  const gaps = m.unableToAssess > 0 || m.documentsUnopened.length > 0

  return (
    <section className="panel assesssummary" style={{ borderLeft: `4px solid ${tone.bar}` }}>

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
            ? `, and ${m.documentsUnopened.length} document${m.documentsUnopened.length === 1 ? '' : 's'} could not be opened`
            : ''}.
        </p>
      )}

      {/* ── The seven, and only these seven ──────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                    gap: 12, marginTop: 16 }}>

        <Metric label="Documents assessed" value={m.documentsAssessed} unit={`of ${m.documentsSelected}`}>
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
            {m.documentsUnopened.length} document{m.documentsUnopened.length === 1 ? '' : 's'} could not be opened
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
            Counted in the {m.documentsSelected} selected and excluded from every other number here.
            They are not passes, not failures and not findings.
          </div>
        </div>
      )}
    </section>
  )
}
