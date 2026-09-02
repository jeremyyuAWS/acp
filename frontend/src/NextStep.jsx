import AccordionSection from './AccordionSection.jsx'
// "NEXT" (approved board 7) — the one thing to do about everything above it.
//
// The Overview answers "where does the estate stand". This answers "so what now", which is the
// question a reader actually leaves with, and it is the only panel on the screen allowed a primary
// action. Everything else here reports.
//
// THE PARTITION, NOT A PERCENTAGE. The board reads "ACP can fix 41% of the findings
// deterministically; the rest need a person." The number is right and the shape is the one this
// redesign spent #545 removing: a bare percentage hides its denominator, and 41% of an unstated
// total is how "51% auto-remediable" got quoted for a year. Same fact, both counts on screen, the
// denominator beside them.
//
// DETERMINISTIC MEANS DETERMINISTIC. `autoFixAvailable` counts findings whose capability lane is
// `auto` — not `assisted`. An AI-drafted fix is advice awaiting a human decision, and counting it
// as automation is precisely the overclaim the metric contract was rewritten to prevent.

const num = (v) => Number(v || 0).toLocaleString()
const plural = (n, one, many) => (n === 1 ? one : many)

/**
 * @param metrics   assessMetrics output, or null. Null renders nothing — a run that has not
 *                  happened has no next step, and inventing one is worse than an empty column.
 * @param awaiting  files still holding an undecided lifecycle recommendation, or null when the
 *                  lifecycle columns never reached this screen. Null omits the line entirely.
 * @param onRemediate  primary action.
 * @param onExport     secondary. Omitted → no button, rather than a dead one.
 * @param onReviewLifecycle  takes the reader to Discover to clear the recommendations.
 */
export default function NextStep({ metrics, awaiting = null, onRemediate, onExport, onReviewLifecycle }) {
  if (!metrics) return null

  const docs = metrics.documentsNeedingAttention
  const total = metrics.totalFindings
  const auto = metrics.autoFixAvailable
  const person = metrics.humanReviewRequired

  // Nothing needs doing is a RESULT, and it is stated as one — with the coverage caveat, because
  // "no findings" over a partly-evaluated estate is the most damaging sentence this product prints.
  const clear = total === 0

  return (
    <AccordionSection id="next-step" title="NEXT" ariaLabel="Next" defaultOpen>

      {clear ? (
        <p style={{ margin: '8px 0 0', fontSize: 13.5, lineHeight: 1.6 }}>
          No unresolved findings in the documents that were assessed.
          <span className="muted"> That is not the same as conformance — the panel above says which
          criteria were evaluated, and a criterion nobody could test is neither a pass nor a failure.</span>
        </p>
      ) : (
        <p style={{ margin: '8px 0 0', fontSize: 13.5, lineHeight: 1.6 }}>
          <b>{num(docs)}</b> {plural(docs, 'document carries', 'documents carry')} at least one
          unresolved finding. Of <b>{num(total)}</b> {plural(total, 'finding', 'findings')}, ACP can
          fix <b>{num(auto)}</b> automatically; the remaining <b>{num(person)}</b> need a person.
        </p>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
        {!clear && onRemediate && (
          <button type="button" onClick={() => onRemediate()}>Go to Remediate</button>
        )}
        {onExport && (
          <button className="ghost" type="button" onClick={() => onExport()}>Export report</button>
        )}
      </div>

      {/* Only when the lifecycle columns actually reached this screen. `null` is "we did not read
          it", which is not the same as "none are waiting" — and the difference matters, because
          this line is the only place an undecided recommendation is surfaced after Discover. */}
      {awaiting != null && awaiting > 0 && (
        <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.55 }}>
          {num(awaiting)} {plural(awaiting, 'file', 'files')} still hold a lifecycle recommendation
          awaiting a decision — they were not assessed.
          {onReviewLifecycle && (
            <> <button className="linklike" type="button" onClick={() => onReviewLifecycle()}>
              Review them on Discover
            </button></>
          )}
        </p>
      )}
    </AccordionSection>
  )
}
