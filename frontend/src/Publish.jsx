import { useState } from 'react'
import FileDrawer from './FileDrawer.jsx'

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

  return (
    <>
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
        <p className="muted" style={{ marginTop: 12 }}>Publishing writes the conformance status back to the source and records the change in the audit trail (see Overview).</p>
      </section>
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}
