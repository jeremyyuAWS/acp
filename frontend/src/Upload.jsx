import { useState, useRef } from 'react'
import { Bars } from './charts.jsx'
import { IDENTITY } from './sim.js'
import Logo from './Logo.jsx'

// Single-document walkthrough: upload → scan → assess → remediate → human review →
// certified. Self-contained demo (no backend); findings are keyed off the file type so
// it reacts to whatever the user actually uploads.
const STEPS = ['Upload', 'Assess', 'Remediate', 'Review', 'Certified']
const EXT_ISSUES = {
  pdf: [['pdf.alt-text', '1.1.1 non-text content', 'CRITICAL', 'figure 2 has no alternative text'], ['pdf.tagged', '1.3.1 info & relationships', 'SERIOUS', 'document is not tagged'], ['pdf.document-language', '3.1.1 language of page', 'MODERATE', 'no document language set']],
  docx: [['DOCX-ALT-001', '1.1.1 non-text content', 'CRITICAL', '3 images missing alt text'], ['DOCX-TITLE-001', '2.4.2 page titled', 'SERIOUS', 'no document title'], ['DOCX-TABLE-001', '1.3.1 info & relationships', 'SERIOUS', 'a table is missing its header row'], ['DOCX-LINK-001', '2.4.4 link purpose', 'MODERATE', '2 ambiguous “click here” links']],
  pptx: [['PPTX-ALT-001', '1.1.1 non-text content', 'CRITICAL', 'chart on slide 4 has no alt text'], ['PPTX-TITLE-001', '2.4.2 page titled', 'SERIOUS', '2 slides are missing titles']],
  xlsx: [['XLSX-ALT-001', '1.1.1 non-text content', 'MODERATE', 'a chart is missing alt text'], ['XLSX-HEADER-001', '1.3.1 info & relationships', 'MODERATE', 'a table has no header row']],
  html: [['WEB-CONTRAST-001', '1.4.3 contrast (AA)', 'SERIOUS', '3 elements below 4.5:1 contrast'], ['WEB-ALT-001', '1.1.1 non-text content', 'CRITICAL', '2 images missing alt'], ['WEB-LABEL-001', '1.3.1 info & relationships', 'MODERATE', 'a form input has no label']],
}
const SEV_PEN = { CRITICAL: 16, SERIOUS: 11, MODERATE: 5, MINOR: 2 }
const SEV_BADGE = { CRITICAL: ['#FCEBEB', '#A32D2D'], SERIOUS: ['#FAECE7', '#993C1D'], MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'] }
const FIX = { 'pdf.alt-text': ['<Figure>', '<Figure alt="bar chart: enrollment by quarter, Q3 highest">'], 'DOCX-ALT-001': ['<img>', '<img alt="org chart — 4 divisions reporting to the CMO">'], 'PPTX-ALT-001': ['<pic alt="">', '<pic alt="revenue by region — West leads at 38%">'], 'WEB-ALT-001': ['<img src="hero.jpg">', '<img src="hero.jpg" alt="clinicians reviewing a scan">'], 'XLSX-ALT-001': ['<chart>', '<chart alt="monthly admissions trend, rising">'] }

const extOf = (name) => { const m = /\.([a-z0-9]+)$/i.exec(name || ''); return (m ? m[1] : 'pdf').toLowerCase() }
const issuesFor = (name) => (EXT_ISSUES[extOf(name)] || EXT_ISSUES.pdf).map(([rule, wcag, sev, detail]) => ({ rule, wcag, sev, detail }))

export default function Upload({ onCertified }) {
  const [step, setStep] = useState(0)
  const [file, setFile] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [phase, setPhase] = useState('')
  const [issues, setIssues] = useState([])
  const [drag, setDrag] = useState(false)

  const start = (f) => {
    setFile(f); setScanning(true); setStep(0)
    const phases = ['Connecting…', 'Reading document…', 'mova Agent classifying & tagging…', 'Analysing against WCAG 2.1 AA…', 'Scoring…']
    let i = 0
    const tick = () => { if (i < phases.length) { setPhase(phases[i++]); setTimeout(tick, 640) } else { setScanning(false); setIssues(issuesFor(f.name)); setStep(1) } }
    setTimeout(tick, 300)
  }
  const onInput = (e) => { const f = e.target.files?.[0]; if (f) start({ name: f.name, size: f.size }) }
  const onDrop = (e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) start({ name: f.name, size: f.size }) }
  const sample = async (name) => {
    try { const r = await fetch(`${import.meta.env.BASE_URL}samples/${name}`); const b = await r.blob(); start({ name, size: b.size }) }
    catch { start({ name, size: 100 * 1024 }) }
  }
  const reset = () => { setStep(0); setFile(null); setIssues([]); setScanning(false) }
  const certify = () => { if (file) onCertified?.({ file: file.name }); setStep(4) }

  const score = Math.max(0, 100 - issues.reduce((a, i) => a + (SEV_PEN[i.sev] || 5), 0))
  const review = issues.slice(-1)
  const autoFixed = issues.slice(0, -1)

  const reportRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const doExport = async () => {
    if (!reportRef.current) return
    setExporting(true)
    try { (await import('./exportPdf.js')).exportReportPDF(reportRef.current, `mova-${(file?.name || 'document').replace(/\.[^.]+$/, '')}-report.pdf`) }
    catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }
  const sevCount = {}; issues.forEach((i) => { sevCount[i.sev] = (sevCount[i.sev] || 0) + 1 })
  const SEVCLR = { CRITICAL: '#A32D2D', SERIOUS: '#E24B4A', MODERATE: '#F5B400', MINOR: '#888780' }
  const sevItems = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].filter((s) => sevCount[s]).map((s) => ({ label: s.toLowerCase(), value: sevCount[s], color: SEVCLR[s] }))
  const today = new Date().toISOString().slice(0, 10)

  return (
    <>
      <div className="upsteps">
        {STEPS.map((s, i) => (
          <div key={s} className={`upstep ${i < step ? 'done' : i === step ? 'on' : ''}`}>
            <span className="upnum">{i < step ? '✓' : i + 1}</span>{s}
          </div>
        ))}
      </div>

      {step === 0 && !scanning && (
        <div className={drag ? 'dropzone over' : 'dropzone'}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={onDrop}>
          <div className="dzicon" aria-hidden="true">⬍</div>
          <div style={{ fontSize: 15 }}>Drag a document here, or <label htmlFor="upfile" className="dzlink">browse</label></div>
          <input id="upfile" type="file" style={{ display: 'none' }} accept=".pdf,.docx,.pptx,.xlsx,.html,.htm" onChange={onInput} />
          <div className="muted" style={{ marginTop: 4 }}>PDF · Word · PowerPoint · Excel · HTML — scanned in your browser, nothing is uploaded anywhere</div>
          <div className="dzsamples">
            <span className="muted">or try a real multi-page sample:</span>
            <button className="ghost small" onClick={() => sample('patient-discharge-instructions.pdf')}>PDF</button>
            <button className="ghost small" onClick={() => sample('benefits-policy.docx')}>Word</button>
            <button className="ghost small" onClick={() => sample('quarterly-town-hall.pptx')}>PowerPoint</button>
            <button className="ghost small" onClick={() => sample('finance-metrics.xlsx')}>Excel</button>
            <button className="ghost small" onClick={() => sample('careers-landing.html')}>HTML</button>
          </div>
        </div>
      )}

      {scanning && (
        <div className="scanprog" role="status" aria-live="polite">
          <div className="scanprogline"><span className="spinner" />{phase}<span className="muted"> · {file?.name}</span></div>
          <div className="track"><i style={{ width: '64%', background: '#F5B400', transition: 'width .4s' }} /></div>
        </div>
      )}

      {step === 1 && (
        <section className="panel">
          <div className="rubrichdr"><h2 style={{ margin: 0 }}>Assessment · <span className="fname" style={{ fontSize: 14 }}>{file?.name}</span></h2>
            <span className="badge" style={{ background: '#FAEEDA', color: '#854F0B' }}>{issues.length} findings</span></div>
          <div className="lift" style={{ margin: '12px 0 16px' }}>
            <div className="liftcol"><div className="liftnum" style={{ color: score >= 90 ? '#3B6D11' : score >= 50 ? '#854F0B' : '#A32D2D' }}>{score}</div><div className="muted">score / 100</div></div>
            <div className="muted" style={{ flex: 1 }}>Scored against WCAG 2.1 AA. {score < 90 ? 'Below the certifiable threshold — remediation needed.' : 'Meets the bar.'}</div>
          </div>
          <div className="findings">
            {issues.map((i, n) => {
              const [bg, fg] = SEV_BADGE[i.sev] || SEV_BADGE.MINOR
              return (
                <div className="finding" key={n}>
                  <span className="badge" style={{ background: bg, color: fg }}>{i.sev.toLowerCase()}</span>
                  <div className="findingmain"><div>{i.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{i.detail}</div></div>
                </div>
              )
            })}
          </div>
          <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 16 }}><button onClick={() => setStep(2)}>Auto-remediate →</button></div>
        </section>
      )}

      {step === 2 && (
        <section className="panel">
          <h2>Automated remediation · {file?.name}</h2>
          <div className="findings" style={{ marginBottom: 14 }}>
            {autoFixed.map((i, n) => (
              <div className="finding" key={n}>
                <span className="badge" style={{ background: '#E7F0DC', color: '#3B6D11' }}>fixed</span>
                <div className="findingmain"><div>{i.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{i.detail}</div></div>
              </div>
            ))}
          </div>
          {autoFixed[0] && FIX[autoFixed[0].rule] && (
            <>
              <div className="muted" style={{ marginBottom: 6 }}>example fix · {autoFixed[0].wcag}</div>
              <div className="diffbox before"><span className="difftag">before</span><code>{FIX[autoFixed[0].rule][0]}</code></div>
              <div className="diffbox after"><span className="difftag">after</span><code>{FIX[autoFixed[0].rule][1]}</code></div>
            </>
          )}
          <p className="muted" style={{ marginTop: 12 }}>{autoFixed.length} issue(s) auto-fixed · <b>{review.length}</b> routed to human review (low confidence).</p>
          <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 4 }}><button onClick={() => setStep(3)}>Human review →</button></div>
        </section>
      )}

      {step === 3 && (
        <section className="panel">
          <h2>Human-in-the-loop review · {file?.name}</h2>
          <div className="queue">
            {review.map((i, n) => (
              <div className="qrow" key={n}>
                <span className="qico" aria-hidden="true">⚑</span>
                <div className="qmain"><div className="qtitle">{i.wcag}</div><div className="qmeta">{i.detail} · agent confidence 52%</div></div>
                <button className="qbtn approve" onClick={certify}>✓ approve</button>
                <button className="qbtn reject" onClick={certify}>✕ reject</button>
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 12 }}>The agent proposes the fix; a reviewer confirms because confidence is below the auto-apply threshold.</p>
        </section>
      )}

      {step === 4 && (
        <>
          <div className="dashtoolbar" style={{ gap: 10 }}>
            <button className="ghost" onClick={reset}>↺ Try another</button>
            <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Download PDF report'}</button>
          </div>
          <div ref={reportRef} className="reportdoc">
            <div className="reporthead">
              <Logo />
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>Accessibility compliance certificate</div>
                <div className="muted">{IDENTITY.org} · WCAG 2.1 AA · {today}</div>
              </div>
            </div>

            <section className="certbanner">
              <div className="certmark" aria-hidden="true">✓</div>
              <div>
                <div className="certtitle">Certified · 100 / 100</div>
                <div className="muted"><span className="fname">{file?.name}</span> passed WCAG 2.1 AA after remediation &amp; re-validation.</div>
              </div>
              <div className="liftgain" style={{ marginLeft: 'auto' }}>{score} → 100</div>
            </section>

            <div className="chartrow">
              <section className="panel"><h2>Compliance lift</h2>
                <div className="lift">
                  <div className="liftcol"><div className="liftnum" style={{ color: '#A32D2D' }}>{score}</div><div className="muted">as received</div></div>
                  <div className="liftarrow" aria-hidden="true">→</div>
                  <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>100</div><div className="muted">certified</div></div>
                </div>
                <p className="muted">{issues.length} finding(s) resolved across {sevItems.length} severity level(s).</p>
              </section>
              <section className="panel"><h2>Findings resolved · by severity</h2>
                {sevItems.length ? <Bars items={sevItems} cols="84px 1fr 28px" /> : <p className="muted">None.</p>}
              </section>
            </div>

            <section className="panel">
              <h2>Issues remediated</h2>
              <div className="findings">
                {issues.map((i, n) => { const [bg, fg] = SEV_BADGE[i.sev] || SEV_BADGE.MINOR; return (
                  <div className="finding" key={n}>
                    <span className="badge" style={{ background: '#E7F0DC', color: '#3B6D11' }}>fixed</span>
                    <div className="findingmain"><div>{i.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{i.detail}</div></div>
                    <span className="badge" style={{ background: bg, color: fg }}>{i.sev.toLowerCase()}</span>
                  </div>
                ) })}
              </div>
            </section>

            <section className="panel">
              <h2>Document journey</h2>
              <div className="journey">
                {['discovered', `assessed ${score}`, 'auto-fixed', 'reviewed', 'certified 100'].map((l, n) => <span className="jstep" key={n}>✓ {l}</span>)}
              </div>
              <p className="muted" style={{ marginTop: 10 }}>Validated against WCAG 2.1 AA · every step captured in the audit trail.</p>
            </section>
          </div>
        </>
      )}
    </>
  )
}
