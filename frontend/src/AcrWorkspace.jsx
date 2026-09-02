import { useCallback, useEffect, useMemo, useState } from 'react'
import AcrCriterionDetail from './AcrCriterionDetail'
import AcrMetadataForm from './AcrMetadataForm'
import AcrPublish from './AcrPublish.jsx'
import { listAcrReports, createAcrReport, getAcrReport, listAcrCriteria, getAcrValidation,
         getAcrPreview, getAcrGaps, downloadAcrPdf } from './acrApi'

// PRD §15 — the ACR list and the report workspace
// (Overview · Criteria · Evidence gaps · Validation · Publication · Draft export).
//
// WHAT THIS SCREEN REFUSES TO DO. It shows no compliance score and no percentage. PRD §4.4 is
// explicit that ACP must make limitations visible rather than optimize for a misleading score, and
// api/accessibility_status.py already states the house rule this follows: "counts only, never a
// percentage of an invented denominator". So the header is "12 of 55 decided", never "22%".
//
// Manual testing and the export-history tabs the PRD also names are Phase 3 and Phase 5; they are
// deliberately absent rather than stubbed, because an empty tab reads as a broken feature and a
// missing one reads as work not yet done.

const TABS = [['overview', 'Overview'], ['criteria', 'Criteria'], ['gaps', 'Evidence gaps'],
              ['validation', 'Validation'], ['publication', 'Publication'],
              ['export', 'Draft export']]

// Criteria filters. "Needs evidence" is deliberately its own filter rather than a status: at 55
// criteria the question an analyst actually has is "where do I still have to go and look", and
// that is not the same set as "undecided" — a criterion can carry a green axe run and still need
// a person (PRD §4.3).
const FILTERS = [
  ['all', 'All'],
  ['undecided', 'Undecided'],
  ['decided', 'Decided'],
  ['unapproved', 'Awaiting approval'],
]

export default function AcrWorkspace() {
  const [reports, setReports] = useState(null)
  const [reportId, setReportId] = useState(null)
  const [report, setReport] = useState(null)
  const [criteria, setCriteria] = useState([])
  const [validation, setValidation] = useState(null)
  const [preview, setPreview] = useState(null)
  const [gapData, setGapData] = useState(null)
  const [tab, setTab] = useState('overview')
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)

  useEffect(() => {
    listAcrReports().then((d) => {
      setReports(d.reports)
      if (d.reports.length && !reportId) setReportId(d.reports[0].id)
    }).catch((e) => setError(String(e.message || e)))
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [])

  const refresh = useCallback(async () => {
    if (!reportId) return
    try {
      const [r, c] = await Promise.all([getAcrReport(reportId), listAcrCriteria(reportId)])
      setReport(r); setCriteria(c.criteria); setError(null)
    } catch (e) { setError(String(e.message || e)) }
  }, [reportId])

  useEffect(() => { refresh() }, [refresh])

  // Validation is fetched for the Overview tab too, not only its own: the metadata form marks a
  // field required from the validation blockers rather than a second hardcoded list, so the form
  // and the publish gate cannot disagree about what is required.
  useEffect(() => {
    if (!reportId) return
    if (tab === 'validation' || tab === 'overview') {
      getAcrValidation(reportId).then(setValidation).catch((e) => setError(String(e.message || e)))
    }
    if (tab === 'export') getAcrPreview(reportId).then(setPreview).catch((e) => setError(String(e.message || e)))
    if (tab === 'gaps') getAcrGaps(reportId).then(setGapData).catch((e) => setError(String(e.message || e)))
  }, [tab, reportId])

  // Which metadata fields the publish gate is currently blocking on, derived from the validation
  // response rather than restated here. `incomplete_metadata` rows name the field in their
  // message ("vendor name is required to publish"), so the field key is recovered from it.
  const metadataBlockers = useMemo(() => {
    const rows = validation?.by_category?.incomplete_metadata || []
    const key = (m) => (m || '').split(' is ')[0].trim().replace(/ /g, '_')
    return {
      blocking: rows.filter((r) => r.blocking).map((r) => key(r.message)),
      advisory: rows.filter((r) => !r.blocking).map((r) => key(r.message)),
    }
  }, [validation])

  const create = async () => {
    setBusy(true); setError(null)
    try {
      const made = await createAcrReport({ product_name: 'ACP by Movate' })
      const d = await listAcrReports()
      setReports(d.reports); setReportId(made.report_id)
    } catch (e) { setError(String(e.message || e)) }
    finally { setBusy(false) }
  }

  if (error && !report) return <p role="alert" className="lockwarn">{error}</p>
  if (reports === null) return <p className="muted">Loading conformance reports…</p>

  if (!reports.length) {
    return (
      <section aria-labelledby="acr-empty-heading">
        <h2 id="acr-empty-heading">Accessibility Conformance Report</h2>
        <p>
          An Accessibility Conformance Report (ACR) records how ACP itself measures against
          WCAG 2.2 Level A and AA, using the VPAT structure procurement teams expect.
        </p>
        <p className="muted">
          Automated results alone never establish conformance — every criterion needs a human
          evaluation and an authorised approver before a report can be published.
        </p>
        <button type="button" onClick={create} disabled={busy}>
          Create Accessibility Conformance Report
        </button>
        {error && <p role="alert" className="lockwarn">{error}</p>}
      </section>
    )
  }

  const shownCriteria = criteria.filter((c) => (
    filter === 'all' ? true
      : filter === 'undecided' ? !c.final_status
        : filter === 'decided' ? !!c.final_status
          : filter === 'unapproved' ? c.approval_state !== 'approved'
            : true))

  const p = report?.progress
  const roles = report?.roles || []
  const canEdit = roles.includes('editor') || roles.includes('approver') || roles.includes('admin')
  const canApprove = roles.includes('approver') || roles.includes('admin')

  return (
    <section aria-labelledby="acr-heading">
      <h2 id="acr-heading">Accessibility Conformance Report</h2>

      {reports.length > 1 && (
        <>
          <label htmlFor="acr-report-picker">Report</label>
          <select id="acr-report-picker" value={reportId || ''}
                  onChange={(e) => { setReportId(e.target.value); setSelected(null) }}>
            {reports.map((r) => (
              <option key={r.id} value={r.id}>
                {r.report_title || r.product_name || r.id} · {r.product_version || 'no version'} · {r.status}
              </option>
            ))}
          </select>
        </>
      )}

      {report && (
        <p className="muted">
          {report.report.product_name} {report.report.product_version || '(no version recorded)'} ·
          {' '}{report.report.vpat_edition} · WCAG {report.report.wcag_version} {report.report.wcag_levels} ·
          {' '}{report.report.status}
        </p>
      )}

      {/* Counts, never a percentage — see the module note. */}
      {p && (
        <p role="status" aria-live="polite">
          {p.decided} of {p.total} criteria decided · {p.approved} approved ·
          {' '}{p.evidence_total} evidence record(s)
          {p.evidence_stale ? ` · ${p.evidence_stale} stale` : ''}
        </p>
      )}

      <nav aria-label="Report sections">
        <ul>
          {TABS.map(([id, label]) => (
            <li key={id}>
              <button type="button" onClick={() => setTab(id)}
                      aria-current={tab === id ? 'page' : undefined}>
                {label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {error && <p role="alert" className="lockwarn">{error}</p>}

      {tab === 'overview' && report && (
        <AcrMetadataForm
          report={report.report}
          blockingFields={metadataBlockers.blocking}
          advisoryFields={metadataBlockers.advisory}
          readOnly={!canEdit || report.report.status === 'published'}
          onSaved={() => {
            refresh()
            getAcrValidation(reportId).then(setValidation).catch(() => {})
          }}
        />
      )}

      {tab === 'gaps' && (
        <div>
          <h3>Evidence gaps</h3>
          {!gapData ? <p className="muted">Checking…</p> : (
            <>
              <p role="status" aria-live="polite">
                {gapData.with_human_evidence} of {gapData.total} criteria have live human
                evidence. {gapData.counts.no_evidence} have none at all,
                {' '}{gapData.counts.automated_only} have only automated results,
                {' '}{gapData.counts.stale_only} have only stale evidence.
              </p>
              <p className="muted">{gapData.note}</p>
              {[['no_evidence', 'No evidence at all'],
                ['automated_only', 'Automated evidence only — a human still has to look'],
                ['stale_only', 'Only stale evidence — retained for audit, cannot support publication']]
                .map(([key, heading]) => {
                  const rows = gapData.buckets[key] || []
                  if (!rows.length) return null
                  return (
                    <section key={key}>
                      <h4>{heading} ({rows.length})</h4>
                      <table>
                        <caption className="sr-only">{heading}</caption>
                        <thead>
                          <tr>
                            <th scope="col">Criterion</th><th scope="col">Level</th>
                            <th scope="col">Evidence</th><th scope="col">Open</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.slice(0, 60).map((r) => (
                            <tr key={r.criterion_num}>
                              <th scope="row">{r.criterion_num} {r.criterion_name}</th>
                              <td>{r.level}</td>
                              <td>{r.evidence_live} live / {r.evidence_total} total</td>
                              <td>
                                <button type="button"
                                        onClick={() => { setSelected(r.criterion_num); setTab('criteria') }}>
                                  Open<span className="sr-only"> {r.criterion_num} {r.criterion_name}</span>
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </section>
                  )
                })}
            </>
          )}
        </div>
      )}

      {tab === 'criteria' && (
        <div>
          <h3>Criteria</h3>
          <fieldset>
            <legend>Filter</legend>
            {FILTERS.map(([id, text]) => (
              <span key={id}>
                <input type="radio" id={`acr-filter-${id}`} name="acr-filter" value={id}
                       checked={filter === id} onChange={() => setFilter(id)} />
                <label htmlFor={`acr-filter-${id}`}>{text}</label>
              </span>
            ))}
          </fieldset>
          {/* The count is announced, so a filter change is perceivable without sight — 4.1.3. */}
          <p role="status" aria-live="polite">
            Showing {shownCriteria.length} of {criteria.length} criteria.
          </p>
          <table>
            <caption className="sr-only">WCAG 2.2 Level A and AA criteria</caption>
            <thead>
              <tr>
                <th scope="col">Criterion</th><th scope="col">Level</th>
                <th scope="col">Conformance level</th><th scope="col">Approval</th>
                <th scope="col">Open</th>
              </tr>
            </thead>
            <tbody>
              {shownCriteria.map((c) => (
                <tr key={c.criterion_num}>
                  <th scope="row">{c.criterion_num} {c.criterion_name}</th>
                  <td>{c.level}</td>
                  <td>
                    {c.final_status || <span className="muted">not yet evaluated</span>}
                    {!c.final_status && c.draft_status && (
                      <><br /><span className="muted">ACP draft suggestion: {c.draft_status}</span></>
                    )}
                  </td>
                  <td>{c.approval_state}</td>
                  <td>
                    <button type="button" onClick={() => setSelected(c.criterion_num)}>
                      Open<span className="sr-only"> {c.criterion_num} {c.criterion_name}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {selected && (
            <AcrCriterionDetail reportId={reportId} criterionNum={selected}
                                canEdit={canEdit} canApprove={canApprove}
                                onChange={refresh} />
          )}
        </div>
      )}

      {tab === 'publication' && (
        <AcrPublish reportId={reportId} onChange={() => {
          load()
          getAcrValidation(reportId).then(setValidation).catch(() => {})
        }} />
      )}

      {tab === 'validation' && (
        <div>
          <h3>Validation</h3>
          {!validation ? <p className="muted">Checking…</p> : (
            <>
              <p role="status" aria-live="polite">
                {validation.summary.may_publish
                  ? 'No blockers — this report is ready for approval.'
                  : `${validation.summary.blocking_count} blocker(s) prevent publication.`}
                {validation.summary.advisory_count ? ` ${validation.summary.advisory_count} advisory note(s).` : ''}
              </p>
              {Object.entries(validation.by_category).map(([cat, rows]) => (
                <section key={cat}>
                  <h4>{validation.category_labels[cat] || cat} ({rows.length})</h4>
                  <ul>
                    {rows.slice(0, 25).map((row, i) => (
                      <li key={i}>
                        {row.message}
                        {!row.blocking && <span className="muted"> — advisory</span>}
                      </li>
                    ))}
                  </ul>
                  {rows.length > 25 && <p className="muted">…and {rows.length - 25} more.</p>}
                </section>
              ))}
            </>
          )}
        </div>
      )}

      {tab === 'export' && (
        <div>
          <h3>Draft export</h3>
          {!preview ? <p className="muted">Building preview…</p> : (
            <>
              {/* The most important sentence on this screen. A preview that looked like a finished
                  VPAT would be the single most consequential thing here to get wrong. */}
              <p className="notice">
                <strong>Draft structural preview.</strong> {preview.template.note}
              </p>
              <p className="muted">
                {Object.entries(preview.totals).map(([k, v]) => `${k}: ${v}`).join(' · ')}
              </p>
              {/* The same rows as the table below, as a tagged PDF/UA-1 document. A conformance
                  report that is itself inaccessible is the one document in this product that
                  cannot be allowed to be (PRD §16), so the download says what it produces —
                  a reader should not have to open it to find out. */}
              <p>
                <button
                  type="button"
                  disabled={pdfBusy}
                  onClick={async () => {
                    setPdfBusy(true)
                    setError(null)
                    try {
                      const { blob, filename } = await downloadAcrPdf(reportId)
                      const url = URL.createObjectURL(blob)
                      const a = document.createElement('a')
                      a.href = url
                      a.download = filename
                      document.body.appendChild(a)
                      a.click()
                      a.remove()
                      URL.revokeObjectURL(url)
                    } catch (e) {
                      // The server's sentence, not "download failed" — a 503 here names the
                      // missing renderer, which is the only thing an operator can act on.
                      setError(String(e.message || e))
                    } finally {
                      setPdfBusy(false)
                    }
                  }}
                >
                  {pdfBusy ? 'Preparing PDF…' : 'Download accessible PDF'}
                </button>
                {' '}
                <span className="muted">Tagged PDF/UA-1 — same rows as below.</span>
              </p>
              <table>
                <caption>WCAG {preview.report.wcag_version} Report</caption>
                <thead>
                  <tr>
                    <th scope="col">Criteria</th><th scope="col">Level</th>
                    <th scope="col">Conformance Level</th>
                    <th scope="col">Remarks and Explanations</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.criteria.map((r) => (
                    <tr key={r.criterion_num}>
                      <th scope="row">{r.criterion_num} {r.criterion_name}</th>
                      <td>{r.level}</td>
                      <td>{r.conformance_level}</td>
                      <td>{r.remarks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </section>
  )
}
