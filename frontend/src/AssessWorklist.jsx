import { useState } from 'react'
import { documentRows, SEVERITIES, SEVERITY_LABEL } from './assessMetrics.js'

// The file worklist — level 2 of the results screen, directly under the summary.
//
// WHY DOCUMENTS AND NOT RULES. Remediation happens to a document: somebody opens one file, fixes
// what is wrong inside it and saves it. A rule-first worklist ("12 images missing alt text") reads
// well and asks one person to open the same board pack five times, once per criterion. The
// criterion grouping still matters, but it belongs INSIDE a file, which is the next screen down.
//
// EVERY NUMBER HERE COMES FROM `documentRows`. Not one of them is computed in this file. The screen
// this replaces led with four counts of "problems" over four unstated denominators, each correct on
// its own, and the only durable fix is that the arithmetic lives in exactly one module. The only
// operation this component performs on a number is ADDITION over the module's own row fields, to
// total the rows it is showing — and it prints the all-rows total beside it so the two can be
// compared rather than confused.
//
// THE ORDER IS NOT "WORST FIRST", AND THAT IS DELIBERATE. `documentRows` ranks by the severity mix
// of the findings that need a PERSON, then by the mix overall, then by name. A document holding ten
// auto-fixable critical findings sits below one holding a single serious finding somebody has to
// judge, because after remediation runs the first is clean and the second still needs an afternoon.
// Attention is the scarce resource on this screen; deterministic fixes cost none of it. This
// component renders that order and never re-sorts — the ranking lives in the module with the
// counts, so the worklist and anything else reading the estate cannot disagree about it.
//
// DE-EMPHASIS IS NOT A FILTER. A demoted row keeps every number and every severity colour it had,
// and says on the row why it is where it is. The failure mode of an ordering rule is that it
// quietly becomes a hiding rule.
//
// WHAT A FILTER MUST NOT DO. Filtering to "needs attention" is the normal way to work this list,
// and it is also the easiest way to make 13 clear documents and 2 unreadable ones disappear from a
// screenshot. So every filter carries its own count whether or not it is selected, the populations
// are named above the table, and a filtered view always prints what it is not showing. You can
// narrow this list; you cannot use it to lose track of how much you narrowed.
//
// A DOCUMENT THAT FAILED TO OPEN IS AN OUTCOME OF THIS RUN, NOT AN EXCLUSION. Discovery is
// metadata-only and never opens a file, so password protection, corruption and unsupported internal
// variants are only discoverable here, by trying to read the document. Calling those "excluded"
// says "we chose not to"; they are "we could not", and only the second tells a reader there is
// something left to chase. They sort last, they carry no counts to misread, and they offer no
// action, because there is no work in them until somebody can open the file.

const SEV_COLOR = { CRITICAL: '#8E1B14', SERIOUS: '#B3261E', MODERATE: '#B07A00', MINOR: '#B9B3BE' }

const STATE_LABEL = {
  attention: 'need attention',
  awaiting_review: 'awaiting review',
  clear: 'with no findings',
  unopened: 'failed to open',
}

// The four filters, in triage order. `clear` deliberately has no button of its own — it is the
// state with no work in it — but its population is named above the table, so choosing a filter
// never makes a document vanish without a number saying how many went with it.
const FILTERS = [
  { key: 'attention', label: 'Needs attention', match: (r) => r.state === 'attention' },
  { key: 'awaiting_review', label: 'Awaiting review', match: (r) => r.state === 'awaiting_review' },
  { key: 'unopened', label: 'Failed to open', match: (r) => r.state === 'unopened' },
  { key: 'all', label: 'All', match: () => true },
]

/** Addition over the module's own row fields. An unopened row has no such field and adds nothing. */
const total = (rows, key) => rows.reduce((a, r) => a + (r[key] || 0), 0)

// A11 progressive disclosure (board 4). Five rows is enough to read the shape of a list without
// scrolling past it on a laptop; a page carries its own count of what it left out, in the same
// units the columns are in, so a screenshot of the first five never reads as the whole worklist.
const PAGE_SIZE = 5

/** Findings of one severity, summed over rows. An unopened row carries no bySeverity and adds nothing. */
const sevTotal = (rows, s) => rows.reduce((a, r) => a + (r.bySeverity?.[s] || 0), 0)

const cap1 = (s) => s.charAt(0).toUpperCase() + s.slice(1)

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

const fname = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12.5 }
const numCell = { fontVariantNumeric: 'tabular-nums', fontWeight: 700, textAlign: 'left' }
const subline = { fontSize: 11, marginTop: 2, lineHeight: 1.45 }

/** One row's severity partition. It sums to the Findings cell beside it, on screen, per row. */
function Severity({ row }) {
  if (!row.totalFindings) return <span className="muted">None</span>
  return (
    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '3px 10px' }}>
      {SEVERITIES.map((s) => (
        <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5,
                               fontVariantNumeric: 'tabular-nums' }}>
          {/* The colour is the shorthand for sighted readers and carries no information on its
              own — the word is always there, just not always drawn. Four spelled-out severities
              per row would bury the counts; four unlabelled dots would leave a screen-reader user
              with "3 5 2 1". */}
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2,
                                            background: SEV_COLOR[s], display: 'inline-block' }} />
          {row.bySeverity[s]}<span className="vh"> {SEVERITY_LABEL[s]}</span>
        </span>
      ))}
      {/* Never dropped. A severity this build does not recognise, silently omitted, would break the
          per-row partition without anything on screen showing that it had. */}
      {row.bySeverity.UNKNOWN > 0 && (
        <span style={{ fontSize: 11.5 }}>{row.bySeverity.UNKNOWN} unclassified</span>
      )}
    </span>
  )
}

/**
 * @param files      the scan's file rows — the same list the summary above is reading
 * @param cap        remediation-capability map
 * @param assessment assessment-lane map
 * @param criteria   the agreed criteria (defaults to the agreed scope inside assessMetrics)
 * @param level      conformance target
 * @param onOpenFile called with the whole row when a document is selected
 */
export default function AssessWorklist({ files, cap, assessment, criteria, level = 'AA', onOpenFile }) {
  const rows = documentRows(files, { cap, assessment, criteria, level })
  // null means "no filter chosen yet", not "all". Resolved below against the rows that actually
  // exist, so the default follows the data as it loads rather than freezing whatever was true on
  // the first render.
  const [chosen, setChosen] = useState(null)
  // A19 severity filter and A24 auto-fixable toggle. Both compose ON TOP of the state filter
  // (ANDed together), and both keep their counts visible whether or not they are selected —
  // narrowing this list must never hide how much it narrowed, the same rule the state filter obeys.
  const [sevChosen, setSevChosen] = useState(null)
  const [autoOnly, setAutoOnly] = useState(false)
  // A11 progressive disclosure. Independent of the filters above — it narrows how much of the
  // FILTERED set is currently rendered, not which rows match. Re-derived from `visible` on every
  // render, so tightening a filter to under PAGE_SIZE rows shows everything with no stale toggle.
  const [expanded, setExpanded] = useState(false)

  // Nothing, rather than zeros. A run that has not happened is not a run that found nothing, and a
  // worklist of no documents is not a worklist. The summary above carries the run's own state.
  if (!rows || rows.length === 0) return null

  const counts = {}
  for (const f of FILTERS) counts[f.key] = rows.filter(f.match).length
  const clear = rows.filter((r) => r.state === 'clear').length

  const active = counts[chosen] ? chosen : (counts.attention ? 'attention' : 'all')
  const stateScoped = rows.filter(FILTERS.find((f) => f.key === active).match)

  // The severity chips and the auto-fixable toggle count over the STATE-SCOPED rows — the exact
  // population the two controls can narrow — so a chip never advertises findings the state filter
  // has already put out of view. Counts are findings, not documents: "Critical 6" is six findings.
  const sevCounts = {}
  let sevAll = 0
  for (const s of SEVERITIES) { sevCounts[s] = sevTotal(stateScoped, s); sevAll += sevCounts[s] }
  const autoFindings = total(stateScoped, 'autoFixAvailable')
  const scopedFindings = total(stateScoped, 'totalFindings')
  const docsWithAuto = stateScoped.filter((r) => (r.autoFixAvailable || 0) > 0).length

  // A severity with no findings in scope cannot be chosen; if the state filter changes out from
  // under a selected severity, fall back to all rather than showing an empty list with no cause.
  const sevActive = sevChosen && sevCounts[sevChosen] > 0 ? sevChosen : null
  let visible = stateScoped
  if (sevActive) visible = visible.filter((r) => (r.bySeverity?.[sevActive] || 0) > 0)
  if (autoOnly) visible = visible.filter((r) => (r.autoFixAvailable || 0) > 0)
  const filtered = visible.length < rows.length
  // The page actually on screen. `hidden` rows are still counted in the totals below — this only
  // ever cuts how many ROWS render, never a number.
  const truncated = !expanded && visible.length > PAGE_SIZE
  const shown = truncated ? visible.slice(0, PAGE_SIZE) : visible
  const hiddenRows = truncated ? visible.slice(PAGE_SIZE) : []

  const populations = [
    ['attention', counts.attention], ['awaiting_review', counts.awaiting_review],
    ['clear', clear], ['unopened', counts.unopened],
  ].filter(([, n]) => n > 0)

  return (
    <section className="panel assessworklist">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                    gap: 12, flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: 15, fontWeight: 650 }}>Documents</span>
          {/* Named above the table so the populations are readable before anything is filtered. */}
          <span className="muted" style={{ fontSize: 12.5 }}>
            {' '}— {populations.map(([k, n]) => `${n} ${STATE_LABEL[k]}`).join(' · ')}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {FILTERS.map((f) => (
            <button key={f.key} type="button" className={f.key === active ? 'small' : 'ghost small'}
                    aria-pressed={f.key === active}
                    disabled={f.key !== 'all' && counts[f.key] === 0}
                    onClick={() => setChosen(f.key)}>
              {f.label} {counts[f.key]}
            </button>
          ))}
        </div>
      </div>

      {/* A19 severity filter + A24 auto-fixable toggle. Shown only when there is finding work in
          scope to narrow — a run with nothing to fix has nothing for either control to do. Every
          chip keeps its count whether selected or not, so a narrowed view still says what it hid. */}
      {scopedFindings > 0 && (
        <div className="worklist-refine" style={{ display: 'flex', alignItems: 'center', gap: 16,
                                                  flexWrap: 'wrap', marginTop: 10 }}>
          {sevAll > 0 && (
            <div role="group" aria-label="Filter documents by finding severity"
                 style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="muted" style={{ fontSize: 11.5 }}>Severity</span>
              <button type="button" className={!sevActive ? 'small' : 'ghost small'}
                      aria-pressed={!sevActive} onClick={() => setSevChosen(null)}>
                All {sevAll}
              </button>
              {SEVERITIES.map((s) => (
                <button key={s} type="button"
                        className={sevActive === s ? 'small' : 'ghost small'}
                        aria-pressed={sevActive === s}
                        disabled={sevCounts[s] === 0}
                        onClick={() => setSevChosen(sevActive === s ? null : s)}>
                  <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, marginRight: 5,
                                                    background: SEV_COLOR[s], display: 'inline-block' }} />
                  {cap1(SEVERITY_LABEL[s])} {sevCounts[s]}
                </button>
              ))}
            </div>
          )}
          <label className="worklist-autoonly" style={{ display: 'inline-flex', alignItems: 'center',
                                                        gap: 7, fontSize: 12.5, cursor: 'pointer' }}>
            <input type="checkbox" checked={autoOnly}
                   onChange={(e) => setAutoOnly(e.target.checked)} />
            <span>Only what ACP can fix without a person</span>
            {/* The toggle carries its own denominator for the same reason the chips do: hiding the
                documents a person must still touch is exactly the mistake this screen guards against. */}
            <span className="muted">
              {autoFindings} of {scopedFindings} findings ·{' '}
              {docsWithAuto} of {plural(stateScoped.length, 'document', 'documents')}
            </span>
          </label>
        </div>
      )}

      {/* The ordering, said out loud. A list whose order carries a judgement and does not name it
          is one people re-sort by hand because they assume it is arbitrary. */}
      <p className="muted" style={{ fontSize: 12, margin: '8px 0 0', lineHeight: 1.6 }}>
        Ordered by what needs a person. A finding ACP fixes deterministically is one button in
        remediation, so it does not move a document up this list — it is still shown, still counted,
        and still on the same row.
      </p>

      <table style={{ marginTop: 10 }}>
        <thead>
          <tr>
            <th scope="col" style={{ width: '38%' }}>Document</th>
            <th scope="col">Findings</th>
            <th scope="col" style={{ width: 190 }}>Severity</th>
            <th scope="col">Auto-fix</th>
            <th scope="col" style={{ width: 130 }}>Needs a person</th>
            <th scope="col"><span className="vh">Action</span></th>
          </tr>
        </thead>
        <tbody>
          {/* documentRows has already ordered these — by what needs a person, then by the overall
              severity mix, then by name, with unopened files last. Re-sorting here would be a
              second ordering rule for the same list, and the two would drift. */}
          {shown.map((row) => (
            <tr key={row.file} className={`worklist-row worklist-${row.state}`}>
              <td>
                <div style={fname}>{row.name}</div>
                <div className="muted" style={subline}>
                  {row.opened
                    ? <>{row.fmt}
                        {row.unassessableCriteria.length > 0
                          ? ` · ${plural(row.unassessableCriteria.length, 'criterion', 'criteria')} `
                            + 'could not be assessed for this format'
                          : ` · all ${plural(row.selectedChecks, 'selected check', 'selected checks')} evaluated`}
                      </>
                    : <>{row.fmt} · could not be opened{row.reason ? ` — ${row.reason}` : ''}</>}
                </div>
                {/* Why this row is low in the list, on the row itself. Without it the ordering is
                    an unexplained demotion of documents that still show red severity dots. */}
                {row.opened && !row.needsPerson && row.totalFindings > 0 && (
                  <div className="worklist-machine-only" style={{ ...subline, color: '#2F7D32' }}>
                    Nothing here needs you — ACP fixes all {row.autoFixAvailable} in remediation
                  </div>
                )}
              </td>
              {row.opened ? (
                <>
                  <td className="col-findings" style={numCell}>
                    <span className="n">{row.totalFindings}</span>
                  </td>
                  <td className="col-severity"><Severity row={row} /></td>
                  <td className="col-auto"
                      style={{ ...numCell, color: row.autoFixAvailable ? '#2F7D32' : undefined }}>
                    <span className="n">{row.autoFixAvailable}</span>
                  </td>
                  <td className="col-person" style={numCell}>
                    <span className="n">{row.humanReviewRequired}</span>
                    {/* The mix the ordering actually keys on, in the same cell as the count it
                        sums to. Two documents with "3" here are not the same work when one of
                        them is three criticals. */}
                    {row.humanReviewRequired > 0 && (
                      <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '2px 8px',
                                     marginLeft: 8, fontWeight: 400 }}>
                        {SEVERITIES.filter((s) => row.bySeverityHuman[s]).map((s) => (
                          <span key={s} style={{ display: 'inline-flex', alignItems: 'center',
                                                 gap: 3, fontSize: 11.5 }}>
                            <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2,
                                                              background: SEV_COLOR[s],
                                                              display: 'inline-block' }} />
                            {row.bySeverityHuman[s]}
                            <span className="vh"> {SEVERITY_LABEL[s]} needing a person</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td className="col-action" style={{ textAlign: 'right' }}>
                    {onOpenFile && (
                      <button className="ghost small" type="button" onClick={() => onOpenFile(row)}>
                        {row.totalFindings ? 'Open findings' : 'Open document'} →
                      </button>
                    )}
                  </td>
                </>
              ) : (
                // No counts at all, rather than zeros: a file ACP never read has no findings, no
                // auto-fixable work and nothing awaiting review, and a 0 in any of those columns
                // would read as a document that came back clean.
                <td className="muted" colSpan={5} style={{ fontSize: 12 }}>
                  No result from this run — it holds no work until the file can be opened.
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {/* A11 · what the PAGE is not showing, distinct from what the FILTER is not showing below.
          Named with the same units the columns are in, exactly as the filter's own "not showing"
          line does — a truncated screenshot must carry its denominator no less than a filtered one. */}
      {truncated && (
        <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
          {shown.length} of {plural(visible.length, 'document', 'documents')} shown —{' '}
          <button type="button" className="linklike" onClick={() => setExpanded(true)}>
            Show the other {hiddenRows.length}
          </button>, which hold {total(hiddenRows, 'totalFindings')} finding
          {total(hiddenRows, 'totalFindings') === 1 ? '' : 's'} between them.
        </div>
      )}

      {/* What the filter is not showing, in the units the columns are in. Printed always, so a
          screenshot of a filtered worklist carries its own denominator. */}
      <div className="muted" style={{ fontSize: 12, marginTop: 10, paddingTop: 9,
                                      borderTop: '1px solid var(--line)', lineHeight: 1.6 }}>
        <div>
          Showing {visible.length} of {plural(rows.length, 'document', 'documents')} —{' '}
          {total(visible, 'totalFindings')} findings · {total(visible, 'autoFixAvailable')} auto-fix ·{' '}
          {total(visible, 'humanReviewRequired')} needing a person
        </div>
        {filtered && (
          <div>
            Across all {rows.length}: {total(rows, 'totalFindings')} findings ·{' '}
            {total(rows, 'autoFixAvailable')} auto-fix ·{' '}
            {total(rows, 'humanReviewRequired')} needing a person
          </div>
        )}
      </div>
    </section>
  )
}
