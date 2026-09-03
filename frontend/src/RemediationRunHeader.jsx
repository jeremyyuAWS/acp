// R1 — the compact run header for the automation-first Remediate tab.
//
// THE SUMMARY LEADS WITH WHAT THE MACHINE ALREADY DID. The old header led with the queue, which
// made a run that fixed 326 things automatically read as 14 items of work. The first segment here
// is always the automation statement, and it is the one segment that still renders at zero —
// "No fixes applied automatically yet" is a fact about the run, not an empty bucket to hide.
//
// UNDEFINED IS NOT ZERO. Every count is optional, and a key the caller did not pass means "this
// screen has not been told", which is a different claim from "there are none of these". Only a
// `typeof n === 'number'` produces a segment; anything else produces nothing at all. Same rule for
// `assessedAt` — when it is null this header says nothing about when the assessment ran rather
// than printing "unknown" or the time it happens to be now.
//
// `completed` IS DELIBERATELY ABSENT FROM THE SUMMARY (§5.3). It is available to the caller for
// `docScope` and for the run-details panel; repeating it in the dominant line makes two elements
// on the same screen assert the same number, and they drift.

// Segment builders, in the order the summary reads them. Each returns a string or null; null is
// dropped. Zero is dropped everywhere EXCEPT autoFixed — see the note above.
function summarySegments(counts) {
  const { autoFixed, needsApproval, manual, revalidating, blocked, documents } = counts || {}
  const out = []

  if (typeof autoFixed === 'number') {
    if (autoFixed === 0) {
      out.push('No fixes applied automatically yet')
    } else {
      const docs = typeof documents === 'number'
        ? ` across ${documents} document${documents === 1 ? '' : 's'}`
        : ''
      out.push(`${autoFixed} fix${autoFixed === 1 ? '' : 'es'} applied automatically${docs}`)
    }
  }
  if (typeof needsApproval === 'number' && needsApproval > 0) out.push(`${needsApproval} need approval`)
  if (typeof manual === 'number' && manual > 0) out.push(`${manual} require manual work`)
  if (typeof revalidating === 'number' && revalidating > 0) out.push(`${revalidating} awaiting revalidation`)
  if (typeof blocked === 'number' && blocked > 0) out.push(`${blocked} blocked`)

  return out
}

/**
 * @param assessedAt        display string for when the assessment ran, or null when not known.
 *                          Null renders NOTHING — never a placeholder date.
 * @param docScope          per-run scope sentence ("84 documents in scope"), or null.
 * @param counts            {autoFixed, needsApproval, manual, revalidating, completed, blocked,
 *                          documents} — every key optional. Undefined means "not known" and is
 *                          omitted; 0 is omitted too except for autoFixed.
 * @param primary           {label, onClick, disabled} — the single state-dependent CTA, or null.
 * @param secondary         {label, onClick, disabled} or null.
 * @param readOnly          historical scan: no actions render at all, and the header says why.
 * @param onOpenRunDetails  () => void. Omit and no "Run details" control renders — this header
 *                          never shows a control for something the parent cannot do.
 */
export default function RemediationRunHeader({
  assessedAt = null,
  docScope = null,
  counts = {},
  primary = null,
  secondary = null,
  readOnly = false,
  onOpenRunDetails = null,
}) {
  const segments = summarySegments(counts)
  // The empty case is a sentence, not a blank line: a header with no summary reads as a component
  // that failed to load rather than a run with nothing to report.
  const empty = segments.length === 0

  return (
    <header aria-label="Remediation run" className="panel"
            style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                     gap: 20, flexWrap: 'wrap' }}>

      <div style={{ minWidth: 260, flex: '1 1 auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 650, color: 'var(--ink)' }}>
            Remediation
          </h2>
          {assessedAt !== null && (
            <span className="muted" style={{ fontSize: 12 }}>Assessment: {assessedAt}</span>
          )}
        </div>

        {/* The summary. Weight and word order carry the emphasis — no segment is distinguished by
            colour alone, so it survives a greyscale render and a screen reader equally. */}
        <p data-testid="rem-run-summary"
           style={{ margin: '6px 0 0', fontSize: 12.5, lineHeight: 1.6,
                    color: 'var(--muted, #54636F)' }}>
          {empty
            ? 'No remediation results yet.'
            : segments.map((s, i) => (
                <span key={s}>
                  {i > 0 ? ' · ' : null}
                  <span style={i === 0 ? { fontWeight: 650, color: 'var(--ink)' } : undefined}>{s}</span>
                </span>
              ))}
        </p>

        {docScope && (
          <p className="muted" style={{ margin: '4px 0 0', fontSize: 12 }}>{docScope}</p>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                    flex: '0 0 auto' }}>
        {readOnly ? (
          // A historical scan has no actions, and saying so is better than a row of dead buttons.
          <span className="muted" style={{ fontSize: 12 }}>Historical scan — read-only.</span>
        ) : (
          <>
            {secondary && (
              <button type="button" className="ghost small"
                      disabled={!!secondary.disabled} onClick={secondary.onClick}>
                {secondary.label}
              </button>
            )}
            {primary && (
              <button type="button" className="primary small"
                      disabled={!!primary.disabled} onClick={primary.onClick}>
                {primary.label}
              </button>
            )}
          </>
        )}
        {onOpenRunDetails && (
          <button type="button" className="linklike" style={{ fontSize: 12 }}
                  onClick={onOpenRunDetails}>
            Run details
          </button>
        )}
      </div>
    </header>
  )
}
