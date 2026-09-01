import { useCallback, useEffect, useState } from 'react'
import AcrCriterionDetail from './AcrCriterionDetail'
import { listAcrReports, createAcrReport, getAcrReport, listAcrCriteria, getAcrValidation,
         getAcrPreview } from './acrApi'

// PRD §15 — the ACR list and the report workspace (Overview · Criteria · Validation · Export).
//
// WHAT THIS SCREEN REFUSES TO DO. It shows no compliance score and no percentage. PRD §4.4 is
// explicit that ACP must make limitations visible rather than optimize for a misleading score, and
// api/accessibility_status.py already states the house rule this follows: "counts only, never a
// percentage of an invented denominator". So the header is "12 of 55 decided", never "22%".
//
// Manual testing and the export-history tabs the PRD also names are Phase 3 and Phase 5; they are
// deliberately absent rather than stubbed, because an empty tab reads as a broken feature and a
// missing one reads as work not yet done.

const TABS = [['overview', 'Overview'], ['criteria', 'Criteria'], ['validation', 'Validation'],
              ['export', 'Draft export']]

export default function AcrWorkspace() {
  const [reports, setReports] = useState(null)
  const [reportId, setReportId] = useState(null)
  const [report, setReport] = useState(null)
  const [criteria, setCriteria] = useState([])
  const [validation, setValidation] = useState(null)
  const [preview, setPreview] = useState(null)
  const [tab, setTab] = useState('overview')
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

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

  useEffect(() => {
    if (!reportId) return
    if (tab === 'validation') getAcrValidation(reportId).then(setValidation).catch((e) => setError(String(e.message || e)))
    if (tab === 'export') getAcrPreview(reportId).then(setPreview).catch((e) => setError(String(e.message || e)))
  }, [tab, reportId])

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
        <div>
          <h3>Report information</h3>
          <table>
            <caption className="sr-only">Report metadata</caption>
            <tbody>
              {Object.entries(report.report)
                .filter(([k]) => !['id', 'owner_email'].includes(k))
                .map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row">{k.replace(/_/g, ' ')}</th>
                    <td>{v == null || v === '' ? <span className="muted">not recorded</span> : String(v)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'criteria' && (
        <div>
          <h3>Criteria</h3>
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
              {criteria.map((c) => (
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
