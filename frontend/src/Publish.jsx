import { useState } from 'react'
import FileDrawer from './FileDrawer.jsx'
import { openReport } from './api.js'
import { IDENTITY } from './sim.js'

const scoreColor = (s) => (s >= 80 ? '#3B6D11' : s >= 50 ? '#854F0B' : '#7B1D1D')

// Step 9 · Publish / Replace / Archive. Re-validated documents are published back
// to their source — replaced in place, the prior version archived, metadata
// updated, and owners notified. Simulated actions on the live certifiable set.
export default function Publish({ run, files = [], certified = [], onPublish }) {
  const ready = files.filter((f) => f.compliant)
  const [done, setDone] = useState({})
  const [sel, setSel] = useState(null)
  const publish = (file) => { setDone((d) => (d[file] ? d : { ...d, [file]: true })); onPublish?.(file) }
  const publishAll = () => { setDone(() => Object.fromEntries(ready.map((f) => [f.file, true]))); ready.forEach((f) => onPublish?.(f.file)) }
  const publishedCount = Object.keys(done).length + certified.length
  const pubStarted = Object.keys(done).length > 0   // zero the outcome cards until the user publishes
  const pct = run?.files ? Math.round((run.certifiable / run.files) * 100) : 0
  const onTrack = pct >= 80 || (run?.avg_score ?? 0) >= 80
  const reportDate = new Date(run?.completed_at || Date.now()).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const publishedList = [...Object.keys(done), ...certified.map((c) => c.file)]

  return (
    <>
      {/* The deliverable: a conformance-report header a compliance officer hands to legal. */}
      <section className="panel" style={{ borderLeft: '4px solid #3B6D11' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 18, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 340px' }}>
            <h2 style={{ margin: 0 }}>📜 Conformance Report</h2>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {IDENTITY.org} · WCAG 2.1 Level AA · generated {reportDate}
            </div>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, margin: '12px 0 0', maxWidth: 620 }}>
              This document estate was assessed against <b>WCAG 2.1 Level AA</b> — the ADA Title II, EAA, and Section 508 legal target.
              <b style={{ color: '#3B6D11' }}> {run?.certifiable ?? 0}</b> of <b>{(run?.files ?? 0).toLocaleString()}</b> documents are certifiable as conformant today ({pct}%){run?.error ? <> · {run.error} could not be analysed</> : null}.
            </p>
          </div>
          <div style={{ textAlign: 'center', minWidth: 124 }}>
            <div style={{ fontSize: 42, fontWeight: 800, color: scoreColor(run?.avg_score ?? 0), lineHeight: 1 }}>{run?.avg_score ?? '—'}</div>
            <div className="muted" style={{ fontSize: 11 }}>estate score / 100</div>
            <span className="badge" style={{ marginTop: 9, display: 'inline-block', background: onTrack ? '#E7F0DC' : '#FAEEDA', color: onTrack ? '#2F5310' : '#854F0B' }}>{onTrack ? '✓ On track to conformant' : '⚠ Action required'}</span>
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="exportbtn" onClick={() => run?.id && openReport(run.id)}>⤓ Download full conformance report (PDF)</button>
        </div>
      </section>

      <div className="metrics">
        <div className="metric"><span>ready to publish</span><b>{ready.length}</b></div>
        <div className="metric"><span>published</span><b style={{ color: pubStarted ? '#3B6D11' : '#9AA1B4' }}>{pubStarted ? publishedCount : 0}</b></div>
        <div className="metric"><span>replaced in place</span><b style={{ color: pubStarted ? undefined : '#9AA1B4' }}>{Object.keys(done).length}</b></div>
        <div className="metric"><span>owners notified</span><b style={{ color: pubStarted ? undefined : '#9AA1B4' }}>{pubStarted ? Object.keys(done).length + certified.length : 0}</b></div>
      </div>

      <section className="panel">
        <h2>What “publish” does <span className="muted">· every re-validated document</span></h2>
        <div className="pubsteps">
          <div className="pubstep"><b>↺ Replace in place</b><span className="muted">the accessible version takes over the original URL / path</span></div>
          <div className="pubstep"><b>📦 Archive prior version</b><span className="muted">the old file is retained for the audit trail</span></div>
          <div className="pubstep"><b>🏷 Update metadata</b><span className="muted">conformance status + scan date written back to the source</span></div>
          <div className="pubstep"><b>✉ Notify stakeholders</b><span className="muted">the document owner is told it’s now compliant</span></div>
        </div>
      </section>

      <section className="panel">
        <div className="rubrichdr">
          <h2 style={{ margin: 0 }}>Publish queue <span className="muted">· {ready.length} re-validated &amp; certifiable</span></h2>
          <button disabled={!ready.length || Object.keys(done).length >= ready.length} onClick={publishAll}>Publish all</button>
        </div>
        {ready.length === 0 ? <p className="muted" style={{ marginTop: 10 }}>Nothing certifiable yet — re-validate fixes in Remediate first.</p> : (
          <div className="publist">
            {ready.map((f) => (
              <div className={`pubrow${done[f.file] ? ' pubdone' : ''}`} key={f.file}>
                <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName} · {f.department}</span></button>
                <span className="badge" style={{ background: '#E7F0DC', color: '#3B6D11' }}>{f.score} / 100</span>
                {done[f.file]
                  ? <span className="okline" style={{ fontSize: 13 }}>✓ published · replaced in place · owner notified</span>
                  : <button className="qbtn approve" onClick={() => publish(f.file)}>↺ Replace &amp; publish</button>}
              </div>
            ))}
          </div>
        )}
        {publishedList.length > 0 ? (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>📋 Audit trail · {publishedList.length} published</div>
            {publishedList.slice(0, 8).map((fname) => (
              <div key={fname} style={{ fontSize: 12.5, padding: '5px 0', borderBottom: '1px solid var(--line)' }}>
                ✓ <b>{fname}</b> <span className="muted">· replaced in place · prior version archived · owner notified · {reportDate}</span>
              </div>
            ))}
            {publishedList.length > 8 && <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>+{publishedList.length - 8} more</div>}
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 12 }}>Publishing writes the conformance status back to the source and records each change in the audit trail here.</p>
        )}
      </section>
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}
