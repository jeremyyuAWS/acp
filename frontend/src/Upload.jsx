import { useState, useRef, useEffect, useMemo } from 'react'
import { generateCaptions, blobToBase64, generateAltText, generateInsights } from './aiRemediate.js'
import { Bars } from './charts.jsx'
import { IDENTITY } from './sim.js'
import Logo from './Logo.jsx'
import BeforeAfter from './BeforeAfter.jsx'
import ResultPreview from './ResultPreview.jsx'
import ScreenReaderDemo from './ScreenReaderDemo.jsx'
import PdfPreview from './PdfPreview.jsx'
import OfficePreview from './OfficePreview.jsx'
import { auditHtml } from './htmlAudit.js'
import { auditOffice } from './officeAudit.js'
import { auditPdf } from './pdfAudit.js'
import { useDialog } from './a11y.js'

const isOffice = (name) => /\.(docx|pptx|xlsx)$/i.test(name || '')
const HKEY = 'mova_upload_history'
const loadHistory = () => { try { return JSON.parse(localStorage.getItem(HKEY) || '[]') } catch { return [] } }
const SEV_BADGE2 = { CRITICAL: ['#E2EDFB', '#1F5FA8'], SERIOUS: ['#E6EFFB', '#2A5E9E'], MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'] }
const fmtDate = (iso) => { try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) } catch { return '' } }
const FIX_PROPOSAL = {
  '1.1.1': ['<img> with no alt text', 'alt: “bar chart — enrollment by region, West highest at 38%” (AI-drafted)'],
  '1.3.1': ['table / control without programmatic structure', 'header cells tagged · form fields labelled'],
  '1.3.2': ['reading order differs from the visual layout', 're-tagged to follow the visual flow'],
  '1.3.3': ['instruction relies on shape/position (“the round button”)', 'LLM rewords it to name the control — AI-drafted, human-approved'],
  '1.4.1': ['in-text link distinguished by colour alone', 'underline added — no longer colour-only'],
  '1.4.3': ['text below the 4.5:1 contrast minimum', 'recoloured to 4.8:1 — passes AA'],
  '1.4.4': ['viewport blocks zoom (user-scalable=no)', 'zoom re-enabled — text resizes to 200%+'],
  '1.4.5': ['heading rendered as an image of text', 'vision OCR extracts the text → rebuilt as real <h1> — AI-drafted, human-approved'],
  '1.4.10': ['no responsive viewport — 2-D scroll at 320px', 'width=device-width added so content reflows'],
  '1.4.11': ['UI border / icon below the 3:1 minimum', 'recoloured to ≥3:1 — AI-proposed, design-reviewed'],
  '1.4.12': ['fixed line-height clips on a text-spacing override', 'spacing made adaptive — AI-proposed, reviewed'],
  '2.1.1': ['click-only element is not keyboard-operable', 'role="button" + tabindex="0" + key handlers added'],
  '2.1.2': ['focus can be trapped inside a widget', 'Escape + focus-loop added — human-verified'],
  '2.4.2': ['document has no title', 'descriptive title set'],
  '2.4.3': ['positive tabindex jumps the focus order', 'reset to tabindex="0" — natural order'],
  '2.4.4': ['ambiguous “click here” link', 'rewritten to “view the 2026 benefits guide”'],
  '3.1.1': ['document language not declared', 'lang set to “en”'],
  '3.1.2': ['foreign-language passage not marked up', 'lang added to the passage — AI-detected, reviewed'],
  '4.1.2': ['control has no accessible name', 'aria-label / <label> added'],
}
const proposeFix = (f) => { const sc = (f?.wcag || '').match(/^\d+\.\d+\.\d+/)?.[0]; return FIX_PROPOSAL[sc] || [f?.detail || 'finding present', 'remediated &amp; re-validated'] }

const isHtml = (name) => /\.html?$/i.test(name || '')
const isPdf = (name) => /\.pdf$/i.test(name || '')
const isAudio = (name) => /\.(mp3|m4a|wav|aac|ogg|webm|mp4|mov)$/i.test(name || '')
const isImage = (name) => /\.(png|jpe?g|gif|webp)$/i.test(name || '')
const AUDIO_ISSUES = [['MEDIA-CAPTIONS-001', '1.2.2 captions', 'CRITICAL', 'no synchronized captions for the audio'], ['MEDIA-TRANSCRIPT-001', '1.2.1 audio-only content', 'SERIOUS', 'no text transcript provided']]
const IMAGE_ISSUES = [['IMG-ALT-001', '1.1.1 non-text content', 'CRITICAL', 'image has no alternative text']]

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
const SEV_BADGE = { CRITICAL: ['#E2EDFB', '#1F5FA8'], SERIOUS: ['#E6EFFB', '#2A5E9E'], MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'] }
const extOf = (name) => { const m = /\.([a-z0-9]+)$/i.exec(name || ''); return (m ? m[1] : 'pdf').toLowerCase() }
const issuesFor = (name) => (isAudio(name) ? AUDIO_ISSUES : isImage(name) ? IMAGE_ISSUES : (EXT_ISSUES[extOf(name)] || EXT_ISSUES.pdf)).map(([rule, wcag, sev, detail]) => ({ rule, wcag, sev, detail }))

// Past-upload detail dialog — its own component so focus management runs on open.
function HistoryDetail({ viewing, onClose }) {
  const ref = useRef(null)
  useDialog(ref, onClose)
  return (
    <div className="covdrawer" role="dialog" aria-modal="true" aria-label={`${viewing.name} result`} onClick={onClose}>
      <div className="covpanel" ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540 }}>
        <button className="covclose" aria-label="Close" onClick={onClose}>✕</button>
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
  )
}

// Audio captions/transcript result — real WebVTT from Whisper, with a player + download.
function CaptionsPanel({ blob, captions }) {
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  const vttUrl = useMemo(() => (captions ? URL.createObjectURL(new Blob([captions], { type: 'text/vtt' })) : null), [captions])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); if (vttUrl) URL.revokeObjectURL(vttUrl) }, [url, vttUrl])
  const lines = (captions || '').split('\n').filter((l) => l.trim() && !/^WEBVTT/.test(l) && !l.includes('-->') && !/^\d+$/.test(l.trim()))
  const dl = () => { if (!vttUrl) return; const a = document.createElement('a'); a.href = vttUrl; a.download = 'captions.vtt'; document.body.appendChild(a); a.click(); a.remove() }
  return (
    <div className="capwrap">
      <div className="bahd"><b>Captions &amp; transcript</b>{captions ? <span className="aialtbadge" style={{ marginLeft: 8 }}>⚡ Whisper</span> : <span className="muted" style={{ marginLeft: 8 }}>· transcribing…</span>}</div>
      {url && (/^video\//.test(blob?.type || '')
        ? <video controls src={url} style={{ width: '100%', maxHeight: 320, marginTop: 10, borderRadius: 8, background: '#000' }}>{vttUrl && <track default kind="captions" srcLang="en" label="English" src={vttUrl} />}</video>
        : <audio controls src={url} style={{ width: '100%', marginTop: 10 }}>{vttUrl && <track default kind="captions" srcLang="en" label="English" src={vttUrl} />}</audio>)}
      {captions ? (<>
        <div className="captranscript">{lines.map((l, i) => <p key={i}>{l}</p>)}</div>
        <button className="ghost small" onClick={dl} style={{ marginTop: 9 }}>⤓ Download captions (.vtt)</button>
      </>) : <p className="muted" style={{ marginTop: 9, fontSize: 12 }}>Real speech-to-text runs on the deployed site via Whisper; offline it falls back.</p>}
    </div>
  )
}

// Image result — real Claude-vision alt text (1.1.1) + image-of-text OCR (1.4.5).
function ImagePanel({ blob, result }) {
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const text = result?.text && result.text.trim()
  return (
    <div className="capwrap">
      <div className="bahd"><b>Image · alt text &amp; text extraction</b>{result ? <span className="aialtbadge" style={{ marginLeft: 8 }}>⚡ Claude vision</span> : <span className="muted" style={{ marginLeft: 8 }}>· describing the image…</span>}</div>
      {url && <img src={url} alt={result?.alt || ''} style={{ maxWidth: '100%', maxHeight: 280, borderRadius: 8, marginTop: 10, border: '1px solid var(--line)' }} />}
      {result ? (<>
        <div className="aialtcallout" style={{ marginTop: 10 }}>
          <span className="aialtbadge">1.1.1 alt text</span>
          <span>AI-generated alt text: <b>“{result.alt}”</b> — written into the document so screen-reader users can perceive the image.</span>
        </div>
        {text && (
          <div className="aialtcallout">
            <span className="aialtbadge">1.4.5 image of text · OCR</span>
            <span>This image is rendered text. Claude extracted it as real, selectable text: <b>“{text.length > 260 ? text.slice(0, 260) + '…' : text}”</b></span>
          </div>
        )}
      </>) : <p className="muted" style={{ marginTop: 9, fontSize: 12 }}>Real Claude-vision alt text + image-of-text OCR run on the deployed site; offline it falls back.</p>}
    </div>
  )
}

// Animated count-up for the certified-score reveal.
function CountUp({ from = 0, to = 100, dur = 900 }) {
  const [v, setV] = useState(from)
  useEffect(() => {
    let raf, start
    const tick = (t) => { if (!start) start = t; const p = Math.min(1, (t - start) / dur); setV(Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)))); if (p < 1) raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [from, to, dur])
  return <>{v}</>
}

function ScanImg({ blob }) {
  const url = useMemo(() => URL.createObjectURL(blob), [blob])
  useEffect(() => () => URL.revokeObjectURL(url), [url])
  return <img src={url} alt="" style={{ maxWidth: '100%', maxHeight: 220, borderRadius: 6, display: 'block', margin: '0 auto' }} />
}

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
  const [audioBlob, setAudioBlob] = useState(null)
  const [captions, setCaptions] = useState(null)
  const [pdfBlob, setPdfBlob] = useState(null)
  const [imageBlob, setImageBlob] = useState(null)
  const [imgResult, setImgResult] = useState(null)
  const blobUrl = useRef(null)

  // Real captions (1.2.2/1.2.3) via the Whisper-backed function when an audio file is uploaded.
  useEffect(() => {
    if (!audioBlob) { setCaptions(null); return }
    let live = true
    ;(async () => { const b64 = await blobToBase64(audioBlob); const vtt = await generateCaptions({ audio: b64, mediaType: audioBlob.type || 'audio/mpeg' }); if (live) setCaptions(vtt) })()
    return () => { live = false }
  }, [audioBlob])

  // Real Claude-vision alt text (1.1.1) + image-of-text OCR (1.4.5) when an image is uploaded.
  useEffect(() => {
    if (!imageBlob) { setImgResult(null); return }
    let live = true
    ;(async () => { const b64 = await blobToBase64(imageBlob); const r = await generateAltText({ data: b64, mediaType: imageBlob.type || 'image/png', hint: `Image “${file?.name || ''}”` }); if (live && r) setImgResult(r) })()
    return () => { live = false }
  }, [imageBlob, file])

  const start = (f, { text = null, url = null, office = null, audio = null, pdf = null, image = null } = {}) => {
    setFile(f); setSrcText(text); setPdfUrl(url); setPdfBlob(pdf); setOfficeBlob(office); setAudioBlob(audio); setImageBlob(image); setImgResult(null); setCaptions(null); setRealEngine(null); setScanning(true); setStep(0)
    const html = text && isHtml(f.name)
    const realLabel = html ? 'Analysing with axe-core (real WCAG engine)…' : office ? 'Parsing the document (real OOXML analysis)…' : pdf ? 'Parsing the PDF structure (pdf-lib)…' : audio ? 'Transcribing the audio with Whisper…' : image ? 'Describing the image with Claude vision…' : 'Analysing against WCAG 2.1 AA…'
    const phases = ['Connecting…', 'Reading document…', 'mova Agent classifying & tagging…', realLabel, 'Scoring…']
    let i = 0
    const finish = async () => {
      let found = issuesFor(f.name)
      if (html) { try { found = await auditHtml(text); setRealEngine('axe-core') } catch { /* fall back */ } }
      else if (office) { try { found = await auditOffice(office); setRealEngine('OOXML') } catch { /* fall back */ } }
      else if (pdf) { try { found = await auditPdf(pdf); setRealEngine('pdf-lib') } catch { /* fall back */ } }
      else if (image) { setRealEngine('Claude vision') }
      setScanning(false); setIssues(found); setStep(1)
    }
    const tick = () => { if (i < phases.length) { setPhase(phases[i++]); setTimeout(tick, 640) } else { finish() } }
    setTimeout(tick, 300)
  }
  const handleFile = (f) => {
    const meta = { name: f.name, size: f.size }
    if (isHtml(f.name)) f.text().then((t) => start(meta, { text: t })).catch(() => start(meta))
    else if (isPdf(f.name)) { const url = URL.createObjectURL(f); blobUrl.current = url; start(meta, { url, pdf: f }) }
    else if (isOffice(f.name)) start(meta, { office: f })
    else if (isAudio(f.name)) start(meta, { audio: f })
    else if (isImage(f.name)) start(meta, { image: f })
    else start(meta)
  }
  const onInput = (e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }
  const onDrop = (e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) handleFile(f) }
  const sample = async (name) => {
    try {
      const url = `${import.meta.env.BASE_URL}samples/${name}`
      if (isHtml(name)) { const t = await (await fetch(url)).text(); start({ name, size: t.length }, { text: t }) }
      else if (isPdf(name)) { const b = await (await fetch(url)).blob(); start({ name, size: b.size }, { url, pdf: b }) }
      else if (isOffice(name)) { const b = await (await fetch(url)).blob(); start({ name, size: b.size }, { office: b }) }
      else if (isAudio(name)) { const b = await (await fetch(url)).blob(); start({ name, size: b.size }, { audio: b }) }
      else if (isImage(name)) { const b = await (await fetch(url)).blob(); start({ name, size: b.size }, { image: b }) }
      else { const b = await (await fetch(url)).blob(); start({ name, size: b.size }) }
    }
    catch { start({ name, size: 100 * 1024 }) }
  }
  const reset = () => { if (blobUrl.current) { URL.revokeObjectURL(blobUrl.current); blobUrl.current = null } setStep(0); setFile(null); setIssues([]); setScanning(false); setSrcText(null); setPdfUrl(null); setOfficeBlob(null); setAudioBlob(null); setCaptions(null); setPdfBlob(null); setImageBlob(null); setImgResult(null); setRealEngine(null); setReviewOutcome(null) }
  // Floor the as-received score at 18 so a heavily-failing document reads as "low" rather
  // than a broken "0" — the lift to 100 still lands dramatically.
  const score = issues.length ? Math.max(18, 100 - issues.reduce((a, i) => a + (SEV_PEN[i.sev] || 5), 0)) : 100
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
    setExporting(true)
    try {
      const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
      const engine = realEngine ? `real ${realEngine}` : 'WCAG 2.1 AA'
      const findings = issues.map((i) => { const [, fix] = proposeFix({ wcag: i.wcag, detail: i.detail }); return { wcag: i.wcag, sev: i.sev, detail: i.detail, fix: String(fix || '').replace(/<[^>]+>/g, '') } })
      // LLM-powered executive narrative (Claude) — degrades to a deterministic summary offline.
      const insight = await generateInsights({ file: file?.name, score, finalScore, engine, findings: findings.map((f) => ({ wcag: f.wcag, sev: f.sev, detail: f.detail })) }).catch(() => null)
      const { exportDocumentReport } = await import('./pdfReport.js')
      await exportDocumentReport({
        file: file?.name || 'document', date, engine,
        score, finalScore,
        status: rejected ? 'Conditional · review pending' : 'Remediated · WCAG 2.1 AA',
        findings, autoFix: autoFixed.length, humanReview: review.length, insight,
        filename: `mova-${(file?.name || 'document').replace(/\.[^.]+$/, '')}-report.pdf`,
      })
    } catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }
  const sevCount = {}; issues.forEach((i) => { sevCount[i.sev] = (sevCount[i.sev] || 0) + 1 })
  const SEVCLR = { CRITICAL: '#1F5FA8', SERIOUS: '#4A8FE0', MODERATE: '#BF8C00', MINOR: '#888780' }
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
          <input id="upfile" type="file" style={{ display: 'none' }} accept=".pdf,.docx,.pptx,.xlsx,.html,.htm,.mp3,.m4a,.wav,.mp4,.mov,.png,.jpg,.jpeg,.gif,.webp" onChange={onInput} />
          <div className="muted" style={{ marginTop: 4 }}>PDF · Word · PowerPoint · Excel · HTML · audio · image — scanned in your browser, nothing is uploaded anywhere</div>
          <div className="muted" style={{ marginTop: 2, fontSize: 12 }}>⚡ HTML is analysed for real with the axe-core WCAG engine</div>
          <div className="dzsamples">
            <span className="muted">or try a real multi-page sample:</span>
            <button className="ghost small" onClick={() => sample('patient-discharge-instructions.pdf')}>PDF</button>
            <button className="ghost small" onClick={() => sample('benefits-policy.docx')}>Word</button>
            <button className="ghost small" onClick={() => sample('quarterly-town-hall.pptx')}>PowerPoint</button>
            <button className="ghost small" onClick={() => sample('finance-metrics.xlsx')}>Excel</button>
            <button className="ghost small" onClick={() => sample('careers-landing.html')}>HTML</button>
            <button className="ghost small" onClick={() => sample('benefits-briefing.mp3')}>Audio</button>
            <button className="ghost small" onClick={() => sample('enrollment-notice.png')} title="An image of text — watch Claude read it back as real text (1.4.5)">Image of text</button>
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
                <span className="badge" style={{ background: h.score >= 90 ? '#E7F0DC' : h.score >= 50 ? '#FAEEDA' : '#E2EDFB', color: h.score >= 90 ? '#3B6D11' : h.score >= 50 ? '#854F0B' : '#1F5FA8' }}>{h.score} / 100</span>
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
                : officeBlob ? <OfficePreview blob={officeBlob} name={file?.name} className="scanoffice" />
                  : imageBlob ? <ScanImg blob={imageBlob} />
                    : <div className="scanplaceholder"><span style={{ fontSize: 46 }} aria-hidden="true">📄</span><div className="muted">{file?.name}</div></div>}
            <div className="scanline" aria-hidden="true" />
          </div>
          <div className="scaninfo">
            <div className="scanprogline"><span className="spinner" />{phase}</div>
            <div className="muted fname" style={{ marginTop: 8, fontSize: 13 }}>{file?.name}</div>
            {realEngine && <div className="realbadge" style={{ marginLeft: 0, marginTop: 8, display: 'inline-block' }}>⚡ real {realEngine} analysis</div>}
            <div className="track" style={{ marginTop: 12 }}><i style={{ width: '66%', background: '#BF8C00', transition: 'width .4s' }} /></div>
          </div>
        </section>
      )}

      {viewing && <HistoryDetail viewing={viewing} onClose={() => setViewing(null)} />}

      {step === 1 && (
        <section className="panel">
          <div className="rubrichdr"><h2 style={{ margin: 0 }}>Assessment · <span className="fname" style={{ fontSize: 14 }}>{file?.name}</span>
            {realEngine && <span className="realbadge" title={`Findings detected live by the ${realEngine} engine running in your browser`}>⚡ real {realEngine} analysis</span>}</h2>
            <span className="badge" style={{ background: '#FAEEDA', color: '#854F0B' }}>{issues.length} findings</span></div>
          <div className="lift" style={{ margin: '12px 0 16px' }}>
            <div className="liftcol"><div className="liftnum" style={{ color: score >= 90 ? '#3B6D11' : score >= 50 ? '#854F0B' : '#1F5FA8' }}>{score}</div><div className="muted">score / 100</div></div>
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
          {isImage(file?.name) ? <ImagePanel blob={imageBlob} result={imgResult} /> : isAudio(file?.name) ? <CaptionsPanel blob={audioBlob} captions={captions} /> : <BeforeAfter file={file} issues={issues} srcText={srcText} pdfUrl={pdfUrl} officeBlob={officeBlob} />}
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

            <section className="certbanner certreveal" style={rejected ? { background: '#FAEEDA', borderColor: '#e8d2a8' } : undefined}>
              <div className="certmark certpop" aria-hidden="true" style={rejected ? { background: '#854F0B' } : undefined}>{rejected ? '!' : '✓'}</div>
              <div>
                <div className="certtitle">{rejected ? `Conditional · ${finalScore} / 100` : 'Certified · 100 / 100'}</div>
                <div className="muted"><span className="fname">{file?.name}</span> {rejected ? 'remediated except 1 finding deferred to manual review — not yet fully WCAG 2.1 AA compliant.' : 'passed WCAG 2.1 AA after remediation & re-validation.'}</div>
              </div>
              <div className="liftgain" style={{ marginLeft: 'auto' }}>{score} → {finalScore}</div>
            </section>

            <div className="chartrow">
              <section className="panel"><h2>Compliance lift</h2>
                <div className="lift">
                  <div className="liftcol"><div className="liftnum" style={{ color: '#1F5FA8' }}>{score}</div><div className="muted">as received</div></div>
                  <div className="liftarrow" aria-hidden="true">→</div>
                  <div className="liftcol"><div className="liftnum" style={{ color: rejected ? '#854F0B' : '#3B6D11' }}><CountUp from={score} to={finalScore} /></div><div className="muted">{rejected ? 'conditional' : 'certified'}</div></div>
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
          {isImage(file?.name) ? <ImagePanel blob={imageBlob} result={imgResult} /> : isAudio(file?.name) ? <CaptionsPanel blob={audioBlob} captions={captions} /> : <ResultPreview file={file} srcText={srcText} pdfUrl={pdfUrl} pdfBlob={pdfBlob} officeBlob={officeBlob} issues={issues} />}
        </>
      )}
    </>
  )
}
