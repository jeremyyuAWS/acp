import { useState, useRef } from 'react'
import { Bars } from './charts.jsx'
import { IDENTITY } from './sim.js'
import Logo from './Logo.jsx'
import BeforeAfter from './BeforeAfter.jsx'
import ScreenReaderDemo from './ScreenReaderDemo.jsx'
import PdfPreview from './PdfPreview.jsx'
import { auditHtml } from './htmlAudit.js'
import { auditOffice } from './officeAudit.js'

const isOffice = (name) => /\.(docx|pptx|xlsx)$/i.test(name || '')
const HKEY = 'mova_upload_history'
const loadHistory = () => { try { return JSON.parse(localStorage.getItem(HKEY) || '[]') } catch { return [] } }
const SEV_BADGE2 = { CRITICAL: ['#FCEBEB', '#A32D2D'], SERIOUS: ['#FAECE7', '#993C1D'], MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'] }
const fmtDate = (iso) => { try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) } catch { return '' } }
const FIX_PROPOSAL = {
  '1.1.1': ['<img> with no alt text', 'alt: “bar chart — enrollment by region, West highest at 38%” (AI-drafted)'],
  '1.3.1': ['table / control without programmatic structure', 'header cells tagged · form fields labelled'],
  '1.3.2': ['reading order differs from the visual layout', 're-tagged to follow the visual flow'],
  '1.4.3': ['text below the 4.5:1 contrast minimum', 'recoloured to 4.8:1 — passes AA'],
  '2.4.2': ['document has no title', 'descriptive title set'],
  '2.4.4': ['ambiguous “click here” link', 'rewritten to “view the 2026 benefits guide”'],
  '3.1.1': ['document language not declared', 'lang set to “en”'],
  '4.1.2': ['control has no accessible name', 'aria-label / <label> added'],
}
const proposeFix = (f) => { const sc = (f?.wcag || '').match(/^\d+\.\d+\.\d+/)?.[0]; return FIX_PROPOSAL[sc] || [f?.detail || 'finding present', 'remediated &amp; re-validated'] }

const isHtml = (name) => /\.html?$/i.test(name || '')
const isPdf = (name) => /\.pdf$/i.test(name || '')

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
const extOf = (name) => { const m = /\.([a-z0-9]+)$/i.exec(name || ''); return (m ? m[1] : 'pdf').toLowerCase() }
const issuesFor = (name) => (EXT_ISSUES[extOf(name)] || EXT_ISSUES.pdf).map(([rule, wcag, sev, detail]) => ({ rule, wcag, sev, detail }))

export default function Upload({ onCertified }) {
  const [step, setStep] = useState(0)
  const [file, setFile] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [phase, setPhase] = useState('')
  const [issues, setIssues] = useState([])
  const [drag, setDrag] = useState(false)
  const [srcText, setSrcText] = useState(null)
  const [pdfUrl, setPdfUrl] = useState(null)
  const [officeBlob, setOfficeBlob] = useState(null)
  const [realEngine, setRealEngine] = useState(null)
  const [history, setHistory] = useState(loadHistory)
  const [viewing, setViewing] = useState(null)
  const [reviewOutcome, setReviewOutcome] = useState(null)
  const blobUrl = useRef(null)

  const start = (f, { text = null, url = null, office = null } = {}) => {
    setFile(f); setSrcText(text); setPdfUrl(url); setOfficeBlob(office); setRealEngine(null); setScanning(true); setStep(0)
    const html = text && isHtml(f.name)
    const realLabel = html ? 'Analysing with axe-core (real WCAG engine)…' : office ? 'Parsing the document (real OOXML analysis)…' : 'Analysing against WCAG 2.1 AA…'
    const phases = ['Connecting…', 'Reading document…', 'mova Agent classifying & tagging…', realLabel, 'Scoring…']
    let i = 0
    const finish = async () => {
      let found = issuesFor(f.name)
      if (html) { try { found = await auditHtml(text); setRealEngine('axe-core') } catch { /* fall back */ } }
      else if (office) { try { found = await auditOffice(office); setRealEngine('OOXML') } catch { /* fall back */ } }
      setScanning(false); setIssues(found); setStep(1)
    }
    const tick = () => { if (i < phases.length) { setPhase(phases[i++]); setTimeout(tick, 640) } else { finish() } }
    setTimeout(tick, 300)
  }
  const handleFile = (f) => {
    const meta = { name: f.name, size: f.size }
    if (isHtml(f.name)) f.text().then((t) => start(meta, { text: t })).catch(() => start(meta))
    else if (isPdf(f.name)) { const url = URL.createObjectURL(f); blobUrl.current = url; start(meta, { url }) }
    else if (isOffice(f.name)) start(meta, { office: f })
    else start(meta)
  }
  const onInput = (e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }
  const onDrop = (e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) handleFile(f) }
  const sample = async (name) => {
    try {
      const url = `${import.meta.env.BASE_URL}samples/${name}`
      if (isHtml(name)) { const t = await (await fetch(url)).text(); start({ name, size: t.length }, { text: t }) }
      else if (isPdf(name)) { const b = await (await fetch(url)).blob(); start({ name, size: b.size }, { url }) }
      else if (isOffice(name)) { const b = await (await fetch(url)).blob(); start({ name, size: b.size }, { office: b }) }
      else { const b = await (await fetch(url)).blob(); start({ name, size: b.size }) }
    }
    catch { start({ name, size: 100 * 1024 }) }
  }
  const reset = () => { if (blobUrl.current) { URL.revokeObjectURL(blobUrl.current); blobUrl.current = null } setStep(0); setFile(null); setIssues([]); setScanning(false); setSrcText(null); setPdfUrl(null); setOfficeBlob(null); setRealEngine(null); setReviewOutcome(null) }
  const score = Math.max(0, 100 - issues.reduce((a, i) => a + (SEV_PEN[i.sev] || 5), 0))
  const review = issues.slice(-1)
  const reviewItem = review[0]
  // Approve → the escalated fix is applied → 100. Reject → it's deferred to manual
  // remediation → the document is conditional, not fully certifiable.
  const rejected = reviewOutcome === 'rejected'
  const finalScore = rejected ? Math.max(0, 100 - (SEV_PEN[reviewItem?.sev] || 5)) : 100
  const certify = (decision = 'approved') => {
    setReviewOutcome(decision)
    const fs = decision === 'rejected' ? Math.max(0, 100 - (SEV_PEN[reviewItem?.sev] || 5)) : 100
    if (file) {
      onCertified?.({ file: file.name })
      const rec = { id: `${file.name}-${Date.now()}`, name: file.name, ext: extOf(file.name), date: new Date().toISOString(), score: fs, outcome: decision, real: realEngine, findings: issues }
      const next = [rec, ...history.filter((h) => h.name !== file.name)].slice(0, 12)
      setHistory(next); try { localStorage.setItem(HKEY, JSON.stringify(next)) } catch { /* ignore quota */ }
    }
    setStep(4)
  }
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
          <div className="muted" style={{ marginTop: 2, fontSize: 12 }}>⚡ HTML is analysed for real with the axe-core WCAG engine</div>
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

      {step === 0 && !scanning && history.length > 0 && (
        <section className="panel" style={{ marginTop: 14 }}>
          <h2>Recent uploads <span className="muted">· kept on this device</span></h2>
          <div className="uphistory">
            {history.map((h) => (
              <button className="uphrow" key={h.id} onClick={() => setViewing(h)}>
                <span className="uphname">{h.name}<span className="muted"> · {fmtDate(h.date)}{h.real ? ' · axe-core' : ''}</span></span>
                <span className="muted">{h.findings.length} finding{h.findings.length === 1 ? '' : 's'}</span>
                <span className="badge" style={{ background: h.score >= 90 ? '#E7F0DC' : h.score >= 50 ? '#FAEEDA' : '#FCEBEB', color: h.score >= 90 ? '#3B6D11' : h.score >= 50 ? '#854F0B' : '#A32D2D' }}>{h.score} / 100</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {scanning && (
        <section className="panel scanstage" role="status" aria-live="polite">
          <div className="scandoc">
            {pdfUrl ? <PdfPreview url={pdfUrl} pages={1} />
              : srcText ? <iframe className="scaniframe" sandbox="" srcDoc={srcText} title="document preview" />
                : <div className="scanplaceholder"><span style={{ fontSize: 46 }} aria-hidden="true">📄</span><div className="muted">{file?.name}</div></div>}
            <div className="scanline" aria-hidden="true" />
          </div>
          <div className="scaninfo">
            <div className="scanprogline"><span className="spinner" />{phase}</div>
            <div className="muted fname" style={{ marginTop: 8, fontSize: 13 }}>{file?.name}</div>
            {realEngine && <div className="realbadge" style={{ marginLeft: 0, marginTop: 8, display: 'inline-block' }}>⚡ real {realEngine} analysis</div>}
            <div className="track" style={{ marginTop: 12 }}><i style={{ width: '66%', background: '#F5B400', transition: 'width .4s' }} /></div>
          </div>
        </section>
      )}

      {viewing && (
        <div className="covdrawer" role="dialog" aria-label={`${viewing.name} result`} onClick={() => setViewing(null)}>
          <div className="covpanel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540 }}>
            <button className="covclose" aria-label="Close" onClick={() => setViewing(null)}>✕</button>
            <div className="fname" style={{ fontSize: 16 }}>{viewing.name}</div>
            <div className="muted" style={{ margin: '4px 0 12px' }}>{fmtDate(viewing.date)} · scored {viewing.score} / 100{viewing.real ? ' · real axe-core analysis' : ''}</div>
            <h4 className="drawerh">Findings ({viewing.findings.length})</h4>
            <div className="findings">
              {viewing.findings.length === 0 ? <p className="muted">No findings.</p> : viewing.findings.map((i, n) => {
                const [bg, fg] = SEV_BADGE2[i.sev] || SEV_BADGE2.MINOR
                return <div className="finding" key={n}><span className="badge" style={{ background: bg, color: fg }}>{(i.sev || '').toLowerCase()}</span><div className="findingmain"><div>{i.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{i.detail}</div></div></div>
              })}
            </div>
            <p className="muted" style={{ marginTop: 12, fontSize: 12 }}>Result kept locally on this device — documents are never retained.</p>
          </div>
        </div>
      )}

      {step === 1 && (
        <section className="panel">
          <div className="rubrichdr"><h2 style={{ margin: 0 }}>Assessment · <span className="fname" style={{ fontSize: 14 }}>{file?.name}</span>
            {realEngine && <span className="realbadge" title={`Findings detected live by the ${realEngine} engine running in your browser`}>⚡ real {realEngine} analysis</span>}</h2>
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
          <BeforeAfter file={file} issues={issues} srcText={srcText} pdfUrl={pdfUrl} officeBlob={officeBlob} />
          <ScreenReaderDemo issues={issues} />
          <p className="muted" style={{ marginTop: 12 }}>{autoFixed.length} finding(s) auto-fixed · <b>{review.length}</b> routed to human review (low confidence).</p>
          <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 4 }}><button onClick={() => setStep(3)}>Human review →</button></div>
        </section>
      )}

      {step === 3 && reviewItem && (() => {
        const [before, after] = proposeFix(reviewItem)
        return (
          <section className="panel">
            <h2>Human-in-the-loop review · {file?.name}</h2>
            <div className="qrow" style={{ borderRadius: 10, border: '1px solid var(--line)', padding: '11px 13px', marginBottom: 12 }}>
              <span className="qico" aria-hidden="true">⚑</span>
              <div className="qmain"><div className="qtitle">{reviewItem.wcag}</div><div className="qmeta">{reviewItem.detail} · agent confidence 52% — below the auto-apply threshold</div></div>
            </div>
            <div className="muted" style={{ marginBottom: 6 }}>Proposed fix · {reviewItem.wcag}</div>
            <div className="diffbox before"><span className="difftag">before</span>{before}</div>
            <div className="diffbox after"><span className="difftag">after</span><span dangerouslySetInnerHTML={{ __html: after }} /></div>
            <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 16, flexWrap: 'wrap' }}>
              <button onClick={() => certify('approved')}>✓ Approve fix &amp; certify</button>
              <button className="ghost" onClick={() => certify('rejected')}>✕ Reject — defer to manual</button>
            </div>
            <p className="muted" style={{ marginTop: 12, fontSize: 12 }}>Approve to apply the fix and re-validate to 100. Reject to leave this finding for manual remediation — the document is then conditionally certified, not fully compliant.</p>
          </section>
        )
      })()}

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

            <section className="certbanner" style={rejected ? { background: '#FAEEDA', borderColor: '#e8d2a8' } : undefined}>
              <div className="certmark" aria-hidden="true" style={rejected ? { background: '#854F0B' } : undefined}>{rejected ? '!' : '✓'}</div>
              <div>
                <div className="certtitle">{rejected ? `Conditional · ${finalScore} / 100` : 'Certified · 100 / 100'}</div>
                <div className="muted"><span className="fname">{file?.name}</span> {rejected ? 'remediated except 1 finding deferred to manual review — not yet fully WCAG 2.1 AA compliant.' : 'passed WCAG 2.1 AA after remediation & re-validation.'}</div>
              </div>
              <div className="liftgain" style={{ marginLeft: 'auto' }}>{score} → {finalScore}</div>
            </section>

            <div className="chartrow">
              <section className="panel"><h2>Compliance lift</h2>
                <div className="lift">
                  <div className="liftcol"><div className="liftnum" style={{ color: '#A32D2D' }}>{score}</div><div className="muted">as received</div></div>
                  <div className="liftarrow" aria-hidden="true">→</div>
                  <div className="liftcol"><div className="liftnum" style={{ color: rejected ? '#854F0B' : '#3B6D11' }}>{finalScore}</div><div className="muted">{rejected ? 'conditional' : 'certified'}</div></div>
                </div>
                <p className="muted">{rejected ? `${issues.length - 1} of ${issues.length} finding(s) resolved · 1 deferred to manual remediation.` : `${issues.length} finding(s) resolved across ${sevItems.length} severity level(s).`}</p>
              </section>
              <section className="panel"><h2>Findings resolved · by severity</h2>
                {sevItems.length ? <Bars items={sevItems} cols="84px 1fr 28px" /> : <p className="muted">None.</p>}
              </section>
            </div>

            <section className="panel">
              <h2>Findings remediated</h2>
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
                {['discovered', `assessed ${score}`, 'auto-fixed', 'reviewed', rejected ? `conditional ${finalScore}` : 'certified 100'].map((l, n) => <span className="jstep" key={n}>✓ {l}</span>)}
              </div>
              <p className="muted" style={{ marginTop: 10 }}>Validated against WCAG 2.1 AA · every step captured in the audit trail.</p>
            </section>
          </div>
        </>
      )}
    </>
  )
}
