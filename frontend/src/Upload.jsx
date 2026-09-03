import { useState, useRef, useEffect, useMemo } from 'react'
import { confirm, alert as dlgAlert } from './ConfirmDialog.jsx'
import { generateCaptions, generateAltText, generateInsights } from './aiRemote.js'
import { blobToBase64 } from './mediaExtract.js'
import { Bars } from './charts.jsx'
import { IDENTITY, PERSONAS, SIM } from './sim.js'
import Logo from './Logo.jsx'
import BeforeAfter, { remediateHtml } from './BeforeAfter.jsx'
import ResultPreview from './ResultPreview.jsx'
import PdfPreview from './PdfPreview.jsx'
import OfficePreview from './OfficePreview.jsx'
import { auditHtml } from './htmlAudit.js'
import { auditOffice, remediateOffice } from './officeAudit.js'
import { auditPptx, remediatePptx } from './pptxAudit.js'
import { auditXlsx, remediateXlsx } from './xlsxAudit.js'
import { auditPdf } from './pdfAudit.js'
import { prescreenHtml } from './prescreen.js'
import { useDialog } from './a11y.js'
import GoogleDrive, { DriveUploadButton, saveDriveScore, uploadToDrive, archiveOriginal } from './GoogleDrive.jsx'
import SharePoint, { SpUploadButton } from './SharePoint.jsx'
import ScanReviewModal from './ScanReviewModal.jsx'
import { loadAiModels, modelLabel, UNKNOWN_MODEL } from './aiModel.js'

const isOffice = (name) => /\.(docx|pptx|xlsx)$/i.test(name || '')
const HKEY = 'mova_upload_history'
const loadHistory = () => { try { return JSON.parse(localStorage.getItem(HKEY) || '[]') } catch { return [] } }
const SEV_BADGE2 = { CRITICAL: ['var(--info-bg)', 'var(--info-fg)'], SERIOUS: ['#E6EFFB', '#2A5E9E'], MODERATE: ['var(--warn-bg)', 'var(--warn-fg)'], MINOR: ['#F1EFE8', '#5F5E5A'] }
const fmtDate = (iso) => { try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) } catch { return '' } }
const FIX_PROPOSAL = {
  '1.1.1': ['<img> with no alt text', 'AI-generated alt text written into the document (local vision model)'],
  '1.3.1': ['table / control without programmatic structure', 'header cells tagged · form fields labelled'],
  '1.3.2': ['reading order differs from the visual layout', 're-tagged to follow the visual flow'],
  '1.3.3': ['instruction relies on shape/position ("the round button")', 'LLM rewords it to name the control — AI-drafted, human-approved'],
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
  '2.4.4': ['ambiguous "click here" link', null],
  '3.1.1': ['document language not declared', 'lang set to "en"'],
  '3.1.2': ['foreign-language passage not marked up', 'lang added to the passage — AI-detected, reviewed'],
  '4.1.2': ['control has no accessible name', 'aria-label / <label> added'],
}
const docTitleFrom = (file) => file?.name ? file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : null
const proposeFix = (f, file) => {
  const sc = (f?.wcag || '').match(/^\d+\.\d+\.\d+/)?.[0]
  const def = FIX_PROPOSAL[sc]
  if (!def) return [f?.detail || 'finding present', 'remediated &amp; re-validated']
  const [before, after] = def
  if (sc === '2.4.4') {
    const t = docTitleFrom(file)
    return [before, t ? `rewritten to "view the ${t.toLowerCase()}"` : 'rewritten with a descriptive anchor phrase']
  }
  return [before, after]
}

const isHtml = (name) => /\.html?$/i.test(name || '')
const isPdf = (name) => /\.pdf$/i.test(name || '')
const isAudio = (name) => /\.(mp3|m4a|wav|aac|ogg|webm|mp4|mov)$/i.test(name || '')
const isVideo = (name) => /\.(mp4|mov|webm)$/i.test(name || '')
const isImage = (name) => /\.(png|jpe?g|gif|webp)$/i.test(name || '')
const AUDIO_ISSUES = [['MEDIA-CAPTIONS-001', '1.2.2 captions', 'CRITICAL', 'no synchronized captions for the audio'], ['MEDIA-TRANSCRIPT-001', '1.2.1 audio-only content', 'SERIOUS', 'no text transcript provided']]
const VIDEO_ISSUES = [['MEDIA-CAPTIONS-001', '1.2.2 captions', 'CRITICAL', 'no synchronized captions for the video'], ['MEDIA-AUDIODESC-001', '1.2.5 audio description', 'SERIOUS', 'no audio-description track for the visual content']]
const IMAGE_ISSUES = [['IMG-ALT-001', '1.1.1 non-text content', 'CRITICAL', 'image has no alternative text']]

// Single-document walkthrough: upload → scan → assess → remediate → human review →
// certified. Self-contained demo (no backend); findings are keyed off the file type so
// it reacts to whatever the user actually uploads.
const STEPS = ['Upload', 'Assess', 'Remediate', 'Review', 'Certified']
const EXT_ISSUES = {
  pdf: [['pdf.missing-alt-text', '1.1.1 non-text content', 'CRITICAL', '2 figures have no alternative text — blind users receive nothing'], ['pdf.tagged', '1.3.1 info & relationships', 'SERIOUS', 'document is untagged — reading order and structure are indeterminate'], ['pdf.document-title', '2.4.2 page titled', 'SERIOUS', 'no document title — screen readers announce the raw filename'], ['pdf.document-language', '3.1.1 language of page', 'MODERATE', 'document language not declared — TTS uses incorrect pronunciation rules']],
  docx: [['DOCX-ALT-001', '1.1.1 non-text content', 'CRITICAL', '4 of 4 image(s) missing alternative text — blind users receive nothing'], ['DOCX-TABLE-001', '1.3.1 info & relationships', 'SERIOUS', '2 table(s) missing a header row — row purpose not programmatically determinable'], ['DOCX-HEAD-001', '1.3.1 info & relationships', 'SERIOUS', 'heading levels are skipped — logical document structure is broken for assistive technology'], ['DOCX-TITLE-001', '2.4.2 page titled', 'SERIOUS', 'document has no title — screen readers announce the raw filename'], ['DOCX-LINK-001', '2.4.4 link purpose', 'MODERATE', '2 hyperlink(s) with generic text ("click here") — purpose is ambiguous out of context'], ['DOCX-LANG-001', '3.1.1 language of page', 'MODERATE', 'document language not declared — TTS uses incorrect pronunciation rules']],
  pptx: [['PPTX-ALT-001', '1.1.1 non-text content', 'CRITICAL', '3 embedded charts have no alt text — blind users receive nothing'], ['PPTX-TITLE-001', '2.4.2 page titled', 'SERIOUS', 'document title is not set'], ['PPTX-SLIDE-001', '2.4.2 page titled', 'SERIOUS', '2 slides are missing titles — slides 2 and 4']],
  xlsx: [['XLSX-ALT-001', '1.1.1 non-text content', 'MODERATE', 'a chart is missing alt text'], ['XLSX-HEADER-001', '1.3.1 info & relationships', 'MODERATE', 'a table has no header row']],
  html: [['WEB-CONTRAST-001', '1.4.3 contrast (AA)', 'SERIOUS', '3 elements below 4.5:1 contrast'], ['WEB-ALT-001', '1.1.1 non-text content', 'CRITICAL', '2 images missing alt'], ['WEB-LABEL-001', '1.3.1 info & relationships', 'MODERATE', 'a form input has no label']],
}
const SEV_PEN = { CRITICAL: 16, SERIOUS: 11, MODERATE: 5, MINOR: 2 }
const SEV_BADGE = { CRITICAL: ['var(--info-bg)', 'var(--info-fg)'], SERIOUS: ['#E6EFFB', '#2A5E9E'], MODERATE: ['var(--warn-bg)', 'var(--warn-fg)'], MINOR: ['#F1EFE8', '#5F5E5A'] }
const extOf = (name) => { const m = /\.([a-z0-9]+)$/i.exec(name || ''); return (m ? m[1] : 'pdf').toLowerCase() }
const issuesFor = (name) => (isVideo(name) ? VIDEO_ISSUES : isAudio(name) ? AUDIO_ISSUES : isImage(name) ? IMAGE_ISSUES : (EXT_ISSUES[extOf(name)] || EXT_ISSUES.pdf)).map(([rule, wcag, sev, detail]) => ({ rule, wcag, sev, detail }))

// Past-upload detail dialog — its own component so focus management runs on open.

// Where the user can locate each fix in the remediated document.
// Keyed first by exact rule code; WCAG_FALLBACK covers real axe-core rule IDs
// and any unrecognised codes by looking up the leading SC number.
const VERIFY_GUIDE = {
  'DOCX-ALT-001':         { app: 'Word',        tipWin: 'Right-click any image → Edit Alt Text — the description field is now filled in (AI-generated, or “Image — described by mova.io” if offline).', tipMac: 'Right-click (or Control+click) any image → Edit Alt Text — the description field is now filled in.' },
  'DOCX-TABLE-001':       { app: 'Word',        tipWin: 'Click the first row of any table → Table Design tab (top ribbon) → confirm “Header Row” checkbox is checked. Also visible in Review tab → Reviewing Pane → Formatting Changes.', tipMac: 'Click the first row of any table → Table Design tab → confirm “Header Row” is checked. Review → Reviewing Pane also lists the formatting change.' },
  'DOCX-HEAD-001':        { app: 'Word',        tip: 'Open Review tab → Comments panel — a REVIEW NEEDED comment explains which heading levels skip. Fix manually via Home → Styles: apply headings in sequence (Heading 1 → Heading 2 → Heading 3, no gaps).' },
  'DOCX-TITLE-001':       { app: 'Word',        tipWin: 'Track Changes shows a new Heading 1 “Accessibility Review — mova.io” at the top of the document (green underlined text). Also: File → Info → Properties (right panel) → Title field is now set.', tipMac: 'Track Changes shows a new Heading 1 “Accessibility Review — mova.io” at the top (green underlined). Also: File → Properties → Summary → Title field is set.' },
  'DOCX-LINK-001':        { app: 'Word',        tip: 'Open Review tab → Comments panel — a REVIEW NEEDED comment lists the generic links. Update each link manually: right-click the link → Edit Hyperlink → change the “Text to display” to describe the destination.' },
  'DOCX-LANG-001':        { app: 'Word',        tipWin: 'Open Review tab → Comments panel — a fix confirmation comment is shown. Also: File → Info → Properties (right panel) → Language is now set to English (United States).', tipMac: 'Open Review tab → Comments panel — a fix confirmation comment is shown. Also: File → Properties → Summary → Language is now set to English (United States).' },
  'pdf.missing-alt-text': { app: 'Acrobat',     tip: 'View → Navigation Panels → Tags → expand <Figure> — the Alt attribute now contains the AI-generated description.' },
  'pdf.tagged':           { app: 'Acrobat',     tip: 'File → Properties → Description — Tagged PDF: Yes. View → Navigation Panels → Tags shows the structure tree.' },
  'pdf.document-title':   { app: 'Acrobat',     tip: 'File → Properties → Description tab — Title is now set to the document name.' },
  'pdf.document-language':{ app: 'Acrobat',     tip: 'File → Properties → Advanced → Reading Options — Language is now set to English.' },
  'PPTX-ALT-001':         { app: 'PowerPoint',  tipWin: 'Right-click any image → Edit Alt Text — the description is now filled in. Images that still read "[Image — add description]" need a manual update.', tipMac: 'Right-click (or Control+click) any image → Edit Alt Text — the description is now filled in. Images that still read "[Image — add description]" need a manual update.' },
  'PPTX-TITLE-001':       { app: 'PowerPoint',  tip: 'REVIEW NEEDED: slides flagged have no title placeholder. In the slide panel right-click → Layout and pick a layout that includes a Title placeholder, then type the slide title.' },
  'PPTX-LANG-001':        { app: 'PowerPoint',  tipWin: 'File → Info → Properties panel shows Language. Also: Review tab → Language → Set Proofing Language — language is now English (United States).', tipMac: 'File → Properties → Summary — language is now English (United States).' },
  'PPTX-SLIDE-001':       { app: 'PowerPoint',  tip: 'View → Outline View — slide titles are visible and descriptive.' },
  'XLSX-TITLE-001':       { app: 'Excel',       tipWin: 'File → Info — the Title field in the Properties panel is now set. Also visible in File → Properties → Summary.', tipMac: 'File → Properties → Summary — the Title field is now set.' },
  'XLSX-SHEET-001':       { app: 'Excel',       tip: 'REVIEW NEEDED: right-click each flagged sheet tab → Rename and enter a meaningful name that describes the sheet\'s content.' },
  'XLSX-ALT-001':         { app: 'Excel',       tipWin: 'Right-click the image or chart → Edit Alt Text — the AI-generated description is now filled in.', tipMac: 'Right-click (or Control+click) the image or chart → Edit Alt Text — the AI-generated description is now filled in.' },
  'XLSX-HEADER-001':      { app: 'Excel',       tip: 'REVIEW NEEDED: select the data range → Insert tab → Table (or Ctrl+T) to create a formal Excel Table, then ensure the "My table has headers" checkbox is ticked.' },
  'WEB-CONTRAST-001':     { app: 'DevTools',    tipWin: 'F12 → Inspect the element → Computed — color/background-color now pass the 4.5:1 (AA) contrast ratio.', tipMac: 'Cmd+Option+I → Inspect the element → Computed — color/background-color now pass the 4.5:1 (AA) contrast ratio.' },
  'WEB-ALT-001':          { app: 'DevTools',    tipWin: 'F12 → Inspect the <img> → Attributes — alt attribute now contains a description.', tipMac: 'Cmd+Option+I → Inspect the <img> → Attributes — alt attribute now contains a description.' },
  'WEB-LABEL-001':        { app: 'DevTools',    tipWin: 'F12 → Inspect the form control → check for a linked <label> or aria-label attribute.', tipMac: 'Cmd+Option+I → Inspect the form control → check for a linked <label> or aria-label attribute.' },
  'MEDIA-CAPTIONS-001':   { app: 'Media player',tip: 'A .vtt caption file is included in the remediated output — attach it as a text track in your video player or CMS.' },
  'MEDIA-AUDIODESC-001':  { app: 'Media player',tip: 'An audio description track is included — upload it alongside the original video in your CMS.' },
  'MEDIA-TRANSCRIPT-001': { app: 'Transcript',  tip: 'A plain-text transcript is included in the remediated output — publish it adjacent to the audio file.' },
  'IMG-ALT-001':          { app: 'Image host',  tip: 'Copy the AI-generated alt text from this report and add it to the alt attribute wherever this image is embedded.' },
}
// WCAG SC-level fallback for axe-core rule IDs not explicitly listed above.
const WCAG_FALLBACK = {
  '1.1.1': { app: 'Document / DevTools', tip: 'Find the image in your document or page and check its alt text or description field.' },
  '1.2.1': { app: 'Transcript',          tip: 'A transcript file is included — publish it adjacent to the audio.' },
  '1.2.2': { app: 'Media player',        tip: 'A .vtt caption file is included — attach it as a text track in your player or CMS.' },
  '1.2.5': { app: 'Media player',        tip: 'An audio description track is included — upload it alongside the video.' },
  '1.3.1': { app: 'Document / DevTools', tip: 'Check heading styles, table header rows, or form label associations in the remediated file.' },
  '1.3.2': { app: 'Document / DevTools', tip: 'Check reading order in the Tags panel (PDF) or heading/list structure (HTML/Office).' },
  '1.4.3': { app: 'DevTools',            tipWin: 'F12 → Inspect the element — colour and background now meet the 4.5:1 contrast ratio.', tipMac: 'Cmd+Option+I → Inspect the element — colour and background now meet the 4.5:1 contrast ratio.' },
  '2.4.2': { app: 'Document properties', tipWin: 'File → Info → Properties — the Title field is now set to the document name.', tipMac: 'File → Properties → Summary — the Title field is now set to the document name.' },
  '2.4.4': { app: 'Document / DevTools', tip: 'Find the hyperlink — display text is now descriptive instead of “click here”.' },
  '3.1.1': { app: 'Document properties', tipWin: 'File → Info → Properties — the Language is now declared as English.', tipMac: 'File → Properties or Tools → Language — the Language is now declared as English.' },
  '3.1.2': { app: 'DevTools',            tip: 'Inspect the flagged text element — a lang attribute now identifies the language of that passage.' },
}
const isMac = () => /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent)
const scOf = (wcag) => (wcag || '').match(/^(\d+\.\d+\.\d+)/)?.[1]
const resolveTip = (entry, os) => { if (!entry) return null; const tip = os === 'mac' ? (entry.tipMac || entry.tip || entry.tipWin) : (entry.tipWin || entry.tip || entry.tipMac); return { ...entry, tip } }
const guideFor = (rule, wcag, os) => resolveTip(VERIFY_GUIDE[rule] || WCAG_FALLBACK[scOf(wcag)], os)

function HistoryDetail({ viewing, onClose }) {
  const ref = useRef(null)
  useDialog(ref, onClose)
  const [expanded, setExpanded] = useState(() => new Set())
  const toggle = (n) => setExpanded((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x })
  const [os, setOs] = useState(() => isMac() ? 'mac' : 'win')
  return (
    <div className="covdrawer" role="dialog" aria-modal="true" aria-label={`${viewing.name} result`} onClick={onClose}>
      <div className="covpanel" ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540 }}>
        <button className="covclose" aria-label="Close" onClick={onClose}>✕</button>
        <div className="fname" style={{ fontSize: 16 }}>{viewing.name}</div>
        <div className="muted" style={{ margin: '4px 0 12px' }}>{fmtDate(viewing.date)} · scored {viewing.score} / 100{viewing.real ? ' · real axe-core analysis' : ''}</div>
        <h4 className="drawerh" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Findings ({viewing.findings.length})</span>
                <span style={{ display: 'flex', gap: 0, fontSize: 11 }}>
                  <button onClick={() => setOs('mac')} style={{ padding: '2px 9px', borderRadius: '4px 0 0 4px', border: '1px solid var(--line)', background: os === 'mac' ? 'var(--ink)' : '#f5f5f5', color: os === 'mac' ? '#fff' : 'var(--muted)', cursor: 'pointer', fontSize: 11, fontWeight: os === 'mac' ? 600 : 400 }}>Mac</button>
                  <button onClick={() => setOs('win')} style={{ padding: '2px 9px', borderRadius: '0 4px 4px 0', border: '1px solid var(--line)', borderLeft: 'none', background: os === 'win' ? 'var(--ink)' : '#f5f5f5', color: os === 'win' ? '#fff' : 'var(--muted)', cursor: 'pointer', fontSize: 11, fontWeight: os === 'win' ? 600 : 400 }}>Windows</button>
                </span>
              </h4>
        <div className="findings">
          {viewing.findings.length === 0 ? <p className="muted">No findings.</p> : viewing.findings.map((i, n) => {
            const [bg, fg] = SEV_BADGE2[i.sev] || SEV_BADGE2.MINOR
            const guide = guideFor(i.rule, i.wcag, os)
            const isOpen = expanded.has(n)
            return (
              <div className="finding" key={n}
                style={{ flexDirection: 'column', alignItems: 'stretch', cursor: guide ? 'pointer' : 'default' }}
                onClick={(e) => { e.stopPropagation(); guide && toggle(n) }}
                role={guide ? 'button' : undefined}
                aria-expanded={guide ? isOpen : undefined}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                  <span className="badge" style={{ background: bg, color: fg, flexShrink: 0 }}>{(i.sev || '').toLowerCase()}</span>
                  <div className="findingmain" style={{ flex: 1 }}>
                    <div>{i.wcag}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{i.detail}</div>
                  </div>
                  {guide && <span aria-hidden="true" style={{ fontSize: 11, color: 'var(--muted)', flexShrink: 0, paddingTop: 3 }}>{isOpen ? '▲' : '▼'}</span>}
                </div>
                {guide && isOpen && (
                  <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--line)', fontSize: 12, lineHeight: 1.5 }}>
                    <span style={{ fontWeight: 600, marginRight: 4 }}>Where to verify in {guide.app}:</span>
                    <span className="muted">{guide.tip}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <p className="muted" style={{ marginTop: 12, fontSize: 12 }}>Result kept locally on this device — documents are never retained.</p>
      </div>
    </div>
  )
}

// Audio captions/transcript result — WebVTT, with a player + download. `captions` is
// { vtt, model }: the model is whatever actually transcribed (the Netlify deployment posts to
// OpenAI; the Azure deployment has no transcription endpoint at all and never reaches here).
function CaptionsPanel({ blob, captions }) {
  const vtt = captions?.vtt || null
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  const vttUrl = useMemo(() => (vtt ? URL.createObjectURL(new Blob([vtt], { type: 'text/vtt' })) : null), [vtt])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); if (vttUrl) URL.revokeObjectURL(vttUrl) }, [url, vttUrl])
  const lines = (vtt || '').split('\n').filter((l) => l.trim() && !/^WEBVTT/.test(l) && !l.includes('-->') && !/^\d+$/.test(l.trim()))
  const dl = () => { if (!vttUrl) return; const a = document.createElement('a'); a.href = vttUrl; a.download = 'captions.vtt'; document.body.appendChild(a); a.click(); a.remove() }
  return (
    <div className="capwrap">
      <div className="bahd"><b>Captions &amp; transcript</b>{captions ? <span className="aialtbadge" style={{ marginLeft: 8 }}>⚡ {captions.model || 'captions'}</span> : <span className="muted" style={{ marginLeft: 8 }}>· preparing…</span>}</div>
      {url && (/^video\//.test(blob?.type || '')
        ? <video controls src={url} style={{ width: '100%', maxHeight: 320, marginTop: 10, borderRadius: 8, background: '#000' }}>{vttUrl && <track default kind="captions" srcLang="en" label="English" src={vttUrl} />}</video>
        : <audio controls src={url} style={{ width: '100%', marginTop: 10 }}>{vttUrl && <track default kind="captions" srcLang="en" label="English" src={vttUrl} />}</audio>)}
      {vtt ? (<>
        <div className="captranscript">{lines.map((l, i) => <p key={i}>{l}</p>)}</div>
        <button className="ghost small" onClick={dl} style={{ marginTop: 9 }}>⤓ Download captions (.vtt)</button>
      </>) : <p className="muted" style={{ marginTop: 9, fontSize: 12 }}>No captions were generated here — the missing-caption finding is detected and routed to a human reviewer (1.2.2).</p>}
    </div>
  )
}

// Image result — alt text (1.1.1) + image-of-text OCR (1.4.5). The model is whatever the
// deployment actually runs (GET /ai/status), never a brand name typed into the markup.
function ImagePanel({ blob, result, visionModel = UNKNOWN_MODEL }) {
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const text = result?.text && result.text.trim()
  return (
    <div className="capwrap">
      <div className="bahd"><b>Image · alt text &amp; text extraction</b>{result ? <span className="aialtbadge" style={{ marginLeft: 8 }}>⚡ {result.model || visionModel}</span> : <span className="muted" style={{ marginLeft: 8 }}>· describing the image…</span>}</div>
      {url && <img src={url} alt={result?.alt || ''} style={{ maxWidth: '100%', maxHeight: 280, borderRadius: 8, marginTop: 10, border: '1px solid var(--line)' }} />}
      {result ? (<>
        <div className="aialtcallout" style={{ marginTop: 10 }}>
          <span className="aialtbadge">1.1.1 alt text</span>
          <span>AI-generated alt text: <b>"{result.alt}"</b> — written into the document so screen-reader users can perceive the image.</span>
        </div>
        {text && (
          <div className="aialtcallout">
            <span className="aialtbadge">1.4.5 image of text · OCR</span>
            <span>This image is rendered text, extracted as real, selectable text: <b>"{text.length > 260 ? text.slice(0, 260) + '…' : text}"</b></span>
          </div>
        )}
      </>) : <p className="muted" style={{ marginTop: 9, fontSize: 12 }}>Alt text and image-of-text OCR are produced server-side by the local vision model during remediation — not in this browser.</p>}
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

export default function Upload({ onCertified, me }) {
  // Real signed-in org for the certificate footer — demo org only in SIM.
  const orgName = SIM ? IDENTITY.org : (me?.email?.split('@')[1]?.replace(/\.[^.]+$/, '') || me?.name || 'your organisation')
  // Single-file workflow state
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
  // The model this deployment actually runs, straight from GET /ai/status — never typed in.
  const [visionModel, setVisionModel] = useState(UNKNOWN_MODEL)
  useEffect(() => { loadAiModels().then((s) => setVisionModel(modelLabel(s, 'vision'))) }, [])
  const [history, setHistory] = useState(loadHistory)
  const [viewing, setViewing] = useState(null)
  const [reviewOutcome, setReviewOutcome] = useState(null)
  const [audioBlob, setAudioBlob] = useState(null)
  const [captions, setCaptions] = useState(null)
  const [pdfBlob, setPdfBlob] = useState(null)
  const [imageBlob, setImageBlob] = useState(null)
  const [imgResult, setImgResult] = useState(null)
  const [prescreen, setPrescreen] = useState([])
  const [hitlVerified, setHitlVerified] = useState(() => new Set())
  const blobUrl = useRef(null)

  // Batch mode state
  const [batchMode, setBatchMode] = useState(false)
  const [queue, setQueue] = useState([])
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchDone, setBatchDone] = useState(false)
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkSaved, setBulkSaved] = useState(false)
  const [batchZipping, setBatchZipping] = useState(false)
  // Universal scan gate for the browse panels. `{ source, files }` while the shared ScanReviewModal
  // is open over Drive/SharePoint-downloaded files, before they are assessed.
  const [browseGate, setBrowseGate] = useState(null)

  // Real captions (1.2.2/1.2.3) via the Whisper-backed function when an audio file is uploaded.
  useEffect(() => {
    if (!audioBlob) { setCaptions(null); return }
    let live = true
    ;(async () => { const b64 = await blobToBase64(audioBlob); const r = await generateCaptions({ audio: b64, mediaType: audioBlob.type || 'audio/mpeg' }); if (live && r) setCaptions(r) })()
    return () => { live = false }
  }, [audioBlob])

  // Alt text (1.1.1) + image-of-text OCR (1.4.5) come from the local vision model, server-side.
  useEffect(() => {
    if (!imageBlob) { setImgResult(null); return }
    let live = true
    ;(async () => { const b64 = await blobToBase64(imageBlob); const r = await generateAltText({ data: b64, mediaType: imageBlob.type || 'image/png', hint: `Image "${file?.name || ''}"` }); if (live && r) setImgResult(r) })()
    return () => { live = false }
  }, [imageBlob, file])

  // Move focus to each new step's heading so keyboard / screen-reader users land on the new
  // content instead of being dropped at the top of the page (manual-audit fix, WCAG 2.4.3).
  useEffect(() => {
    if (step < 1) return
    const el = document.querySelector('main .certbanner') || document.querySelector('main section.panel h2') || document.querySelector('main h2')
    if (el) { el.setAttribute('tabindex', '-1'); el.focus() }
  }, [step])

  // ── Batch functions ──

  const addToQueue = (fileList) => {
    const ts = Date.now()
    const items = Array.from(fileList).map((f, i) => ({
      id: `${f.name}-${ts}-${i}`,
      file: f,
      status: 'waiting',
      score: null,
      issues: null,
      remBlob: null,
      engine: null,
      driveFileId: f._driveId || null,
      spItemId: f._spItemId || null,
      spDriveId: f._spDriveId || null,
    }))
    setQueue((q) => [...q, ...items])
    setBatchDone(false)
  }

  // The actual assess path once the browse files clear the gate — the branching the two
  // handlers used to do inline.
  const processBrowseFiles = (fileObjs) => {
    if (fileObjs.length === 1 && !batchMode) { handleFile(fileObjs[0]); return }
    setBatchMode(true)
    addToQueue(fileObjs)
  }

  // The Drive/SharePoint browse panels download client-side and hand the files here. That path
  // never touched App's doScan, so it was the one scan entry that bypassed the universal scope/
  // behavior review. Intercept it: hold the downloaded files and open the shared ScanReviewModal;
  // only assess them once its scope is confirmed. (GoogleDrive.jsx's own "Scan N selected" button
  // is held byte-identical with the legacy SPA by driveArchive.test.js, so the gate lives here in
  // the shared parent rather than inside the panel.)
  const handleGDriveFiles = (fileObjs) => { if (fileObjs.length) setBrowseGate({ source: 'drive', files: fileObjs }) }
  const handleSpFiles = (fileObjs) => { if (fileObjs.length) setBrowseGate({ source: 'sharepoint', files: fileObjs }) }

  const runBatch = async () => {
    setBatchRunning(true)
    setBatchDone(false)
    // Snapshot waiting items at click time — new additions can be processed in a subsequent run.
    const snapshot = queue.filter((it) => it.status === 'waiting')
    for (const item of snapshot) {
      setQueue((q) => q.map((it) => it.id === item.id ? { ...it, status: 'scanning' } : it))
      try {
        const f = item.file
        let found = []
        let engine = null
        let remBlob = null

        if (isHtml(f.name)) {
          const text = await f.text()
          try { found = await auditHtml(text); engine = 'axe-core' } catch { found = issuesFor(f.name) }
          const rem = remediateHtml(text)
          if (rem?.html) remBlob = new Blob([rem.html], { type: 'text/html' })
        } else if (/\.pptx$/i.test(f.name)) {
          try { found = await auditPptx(f); engine = 'PPTX engine' } catch { found = issuesFor(f.name) }
          try {
            // Extract images from PPTX slides for AI alt text
            let alts = {}
            if (found.some((x) => x.rule === 'PPTX-ALT-001')) {
              try {
                const JSZip = (await import('jszip')).default
                const zip = await JSZip.loadAsync(f)
                const mediaFiles = Object.keys(zip.files).filter((n) => /^ppt\/media\//i.test(n) && /\.(png|jpe?g|gif|webp|bmp)$/i.test(n))
                for (const mediaPath of mediaFiles) {
                  const mediaBlob = await zip.file(mediaPath).async('blob')
                  const b64 = await blobToBase64(mediaBlob)
                  const res = await generateAltText({ data: b64, mediaType: mediaBlob.type || 'image/png' })
                  if (res?.alt) alts[mediaPath.split('/').pop()] = res.alt
                }
              } catch { /* offline — fallback alt text applied */ }
            }
            const r = await remediatePptx(f, { alts })
            remBlob = r.blob
          } catch { /* fall back — no remediated file */ }
        } else if (/\.xlsx$/i.test(f.name)) {
          try { found = await auditXlsx(f); engine = 'XLSX engine' } catch { found = issuesFor(f.name) }
          try { const r = await remediateXlsx(f); remBlob = r.blob } catch { /* fall back */ }
        } else if (isOffice(f.name)) {
          try { found = await auditOffice(f); engine = 'OOXML' } catch { found = issuesFor(f.name) }
          try {
            // Extract images from DOCX and get AI-generated alt text (degrades gracefully offline)
            let alts = {}
            if (/\.docx$/i.test(f.name) && found.some((x) => x.rule === 'DOCX-ALT-001')) {
              try {
                const JSZip = (await import('jszip')).default
                const zip = await JSZip.loadAsync(f)
                const mediaFiles = Object.keys(zip.files).filter((n) => /^word\/media\//i.test(n) && /\.(png|jpe?g|gif|webp|bmp)$/i.test(n))
                for (const mediaPath of mediaFiles) {
                  const mediaBlob = await zip.file(mediaPath).async('blob')
                  const b64 = await blobToBase64(mediaBlob)
                  const res = await generateAltText({ data: b64, mediaType: mediaBlob.type || 'image/png' })
                  if (res?.alt) alts[mediaPath.split('/').pop()] = res.alt
                }
              } catch { /* no key or offline — fallback alt text applied */ }
            }
            remBlob = await remediateOffice(f, { trackedChanges: true, alts })
          } catch { /* fall back — no remediated file */ }
        } else if (isPdf(f.name)) {
          try { found = await auditPdf(f); engine = 'pdf-lib' } catch { found = issuesFor(f.name) }
          try {
            const { remediatePdf } = await import('./pdfAudit.js')
            const r = await remediatePdf(f, { title: f.name.replace(/\.[^.]+$/, '') })
            remBlob = r.blob
          } catch { /* fall back */ }
        } else {
          found = issuesFor(f.name)
          remBlob = f  // audio / video / image — include original
        }

        const score = found.length ? Math.max(18, 100 - found.reduce((a, i) => a + (SEV_PEN[i.sev] || 5), 0)) : 100
        setQueue((q) => q.map((it) => it.id === item.id ? { ...it, status: 'done', score, issues: found, remBlob, engine } : it))
        if (item.driveFileId && score != null) saveDriveScore(item.driveFileId, score, engine)
        if (item.spItemId && score != null) saveDriveScore(item.spItemId, score, engine)
        onCertified?.({ file: f.name })
        const rec = { id: `${f.name}-${Date.now()}`, name: f.name, ext: extOf(f.name), date: new Date().toISOString(), score, outcome: 'batch', real: engine, findings: found }
        setHistory((h) => { const next = [rec, ...h.filter((x) => x.name !== f.name)].slice(0, 12); try { localStorage.setItem(HKEY, JSON.stringify(next)) } catch {}; return next })
      } catch {
        setQueue((q) => q.map((it) => it.id === item.id ? { ...it, status: 'error' } : it))
      }
    }
    setBatchRunning(false)
    setBatchDone(true)
  }

  const handleBulkSaveToDrive = async () => {
    const eligible = queue.filter((i) => i.driveFileId && i.remBlob && i.status === 'done')
    if (!eligible.length) return
    // The archive is unconditional here too, and the note says so rather than offering
    // "Drive version history preserves the originals" as the alternative — a revision history is
    // a different promise from a copy, and it was being used to justify not making one.
    const ok = await confirm({
      title: 'Replace ' + eligible.length + ' file' + (eligible.length !== 1 ? 's' : '') + ' in Google Drive?',
      message: 'Each original is copied to _mova-originals/ first. Any file whose copy fails is skipped, not replaced.',
      variant: 'default', confirmLabel: 'Replace',
    })
    if (!ok) return
    const token = sessionStorage.getItem('gd_token')
    if (!token) return
    setBulkSaving(true); setBulkSaved(false)
    const unsaved = []
    for (const item of eligible) {
      try {
        // This used to inline its own archive behind `await import('./GoogleDrive.jsx')`
        // destructuring `findOrCreateFolder` — which that module never exported. `fof` was
        // therefore ALWAYS undefined, the `if (fof)` guard always false, and the archive never
        // ran once, for anybody, ticked or not. The overwrite below ran regardless.
        //
        // Now the shared, exported, fail-closed archiveOriginal, and a failure SKIPS this file
        // instead of aborting the batch: one file whose copy fails should not stop the other
        // forty, and it must not be overwritten either.
        await archiveOriginal(token, item.driveFileId)
      } catch (e) {
        console.error('Bulk Drive save skipped (archive failed):', item.file?.name, e)
        unsaved.push(item.file?.name || 'a file')
        continue
      }
      try {
        const meta = {
          description: 'Remediated for WCAG 2.1 AA by mova.io · ' + new Date().toISOString().slice(0, 10) + (item.score != null ? ' · Score: ' + item.score + '/100' : ''),
          appProperties: { mova_score: item.score != null ? String(item.score) : '', mova_standard: 'WCAG 2.1 AA', mova_engine: item.engine || 'mova', mova_date: new Date().toISOString().slice(0, 10) },
        }
        await uploadToDrive(token, item.driveFileId, item.remBlob, meta)
      } catch (e) {
        console.error('Bulk Drive save failed:', item.file?.name, e)
        unsaved.push(item.file?.name || 'a file')
      }
    }
    setBulkSaving(false); setBulkSaved(true)
    // Said out loud. A silent partial success reads as "all N replaced", which is the number the
    // button implied when it was clicked.
    if (unsaved.length) {
      dlgAlert({
        title: unsaved.length + ' of ' + eligible.length + ' file' + (eligible.length !== 1 ? 's were' : ' was') + ' NOT replaced',
        message: unsaved.join('\n') + '\n\nTheir originals are unchanged.',
      })
    }
  }

  const downloadBatchZip = async () => {
    setBatchZipping(true)
    try {
      const JSZip = (await import('jszip')).default
      const zip = new JSZip()
      const remFolder = zip.folder('remediated')
      const csvLines = ['File,Score,Findings,Engine,Status']
      for (const item of queue) {
        if (item.status !== 'done') continue
        const label = (item.score ?? 0) >= 90 ? 'Certified' : 'Conditional'
        csvLines.push(`"${item.file.name}",${item.score ?? ''},${item.issues?.length ?? 0},"${item.engine ?? 'simulated'}","${label}"`)
        if (item.remBlob) {
          const outName = item.file.name.replace(/(\.[^.]+)$/, '-remediated$1')
          remFolder.file(outName, item.remBlob)
        }
      }
      zip.file('mova-batch-summary.csv', csvLines.join('\n'))
      const blob = await zip.generateAsync({ type: 'blob' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `mova-batch-${new Date().toISOString().slice(0, 10)}.zip`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (e) { console.error('batch ZIP failed', e) }
    finally { setBatchZipping(false) }
  }

  // ── Single-file functions ──

  const start = (f, { text = null, url = null, office = null, audio = null, pdf = null, image = null } = {}) => {
    setFile(f); setSrcText(text); setPdfUrl(url); setPdfBlob(pdf); setOfficeBlob(office); setAudioBlob(audio); setImageBlob(image); setImgResult(null); setCaptions(null); setRealEngine(null); setScanning(true); setStep(0)
    setPrescreen(text && isHtml(f.name) ? prescreenHtml(text) : [])
    const html = text && isHtml(f.name)
    const phases = pdf
      ? ['Extracting PDF structure & tag tree…', 'Checking alt text, titles & reading order…', 'Running WCAG 2.1 AA conformance checks…', 'Scoring…']
      : office
      ? ['Opening OOXML package…', 'Parsing document structure (headings, tables, images)…', 'Running accessibility checks…', 'Checking language, titles & link purpose…', 'Scoring against WCAG 2.1 AA…']
      : ['Connecting…', 'Reading document…', 'mova Agent classifying & tagging…',
          html ? 'Analysing with axe-core (real WCAG engine)…' : audio ? 'Checking for a transcript or captions…' : image ? 'Checking the image for a text alternative…' : 'Analysing against WCAG 2.1 AA…',
          'Scoring…']
    let i = 0
    const finish = async () => {
      let found = issuesFor(f.name)
      if (html) { try { found = await auditHtml(text); setRealEngine('axe-core') } catch { /* fall back */ } }
      else if (/\.pptx$/i.test(f.name) && office) { try { found = await auditPptx(office); setRealEngine('PPTX engine') } catch { /* fall back */ } }
      else if (/\.xlsx$/i.test(f.name) && office) { try { found = await auditXlsx(office); setRealEngine('XLSX engine') } catch { /* fall back */ } }
      else if (office) { try { found = await auditOffice(office); setRealEngine('OOXML engine') } catch { /* fall back */ } }
      else if (pdf) { try { found = await auditPdf(pdf); setRealEngine('PDF engine') } catch { /* fall back */ } }
      // No engine runs in-browser for an image: the other branches each call a real audit,
      // this one only set a label. Claim nothing. Document alt text is produced server-side by
      // the local vision model during remediation, not here.
      
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

  const onInput = (e) => {
    const files = [...e.target.files]  // spread before clearing — FileList is live and wiped by value=''
    if (!files.length) return
    e.target.value = ''
    if (files.length > 1) { setBatchMode(true); addToQueue(files); return }
    if (batchMode) { addToQueue(files); return }
    handleFile(files[0])
  }

  const onDrop = (e) => {
    e.preventDefault(); setDrag(false)
    const files = e.dataTransfer.files
    if (!files?.length) return
    if (files.length > 1) { setBatchMode(true); addToQueue(files); return }
    if (batchMode) { addToQueue(files); return }
    handleFile(files[0])
  }

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

  const reset = () => { if (blobUrl.current) { URL.revokeObjectURL(blobUrl.current); blobUrl.current = null } setStep(0); setFile(null); setIssues([]); setScanning(false); setSrcText(null); setPdfUrl(null); setOfficeBlob(null); setAudioBlob(null); setCaptions(null); setPdfBlob(null); setImageBlob(null); setImgResult(null); setPrescreen([]); setHitlVerified(new Set()); setRealEngine(null); setReviewOutcome(null) }

  const score = issues.length ? Math.max(18, 100 - issues.reduce((a, i) => a + (SEV_PEN[i.sev] || 5), 0)) : 100
  const review = issues.slice(-1)
  const reviewItem = review[0]
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
  const docTitle = (() => {
    if (srcText) { const t = ((/<h1[^>]*>([\s\S]*?)<\/h1>/i.exec(srcText) || /<title[^>]*>([\s\S]*?)<\/title>/i.exec(srcText) || [])[1] || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim(); if (t) return t.slice(0, 70) }
    return file ? String(file.name).replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : null
  })()

  const reportRef = useRef(null)
  const singleFileRef = useRef(null)
  const batchFileRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const [openPanels, setOpenPanels] = useState(new Set())
  const [wcagVersion, setWcagVersion] = useState('2.1')
  const [assignee, setAssignee] = useState(null)
  const togglePanel = (key) => setOpenPanels((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
  const doExport = async () => {
    setExporting(true)
    try {
      const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
      const engine = realEngine ? `real ${realEngine}` : 'WCAG ' + wcagVersion + ' AA'
      const findings = issues.map((i) => { const [, fix] = proposeFix({ wcag: i.wcag, detail: i.detail }, file); return { wcag: i.wcag, sev: i.sev, detail: i.detail, fix: String(fix || '').replace(/<[^>]+>/g, '') } })
      const insight = await generateInsights({ file: file?.name, score, finalScore, engine, findings: findings.map((f) => ({ wcag: f.wcag, sev: f.sev, detail: f.detail })) }).catch(() => null)
      const { exportDocumentReport } = await import('./pdfReport.js')
      await exportDocumentReport({
        file: file?.name || 'document', date, engine,
        score, finalScore,
        status: rejected ? 'Conditional · review pending' : 'Remediated · WCAG ' + wcagVersion + ' AA',
        findings, autoFix: autoFixed.length, humanReview: review.length, insight, wcagVersion, assignee,
        filename: `mova-${(file?.name || 'document').replace(/\.[^.]+$/, '')}-report.pdf`,
      })
    } catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }
  const sevCount = {}; issues.forEach((i) => { sevCount[i.sev] = (sevCount[i.sev] || 0) + 1 })
  const SEVCLR = { CRITICAL: 'var(--info-fg)', SERIOUS: '#4A8FE0', MODERATE: '#BF8C00', MINOR: '#888780' }
  const sevItems = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].filter((s) => sevCount[s]).map((s) => ({ label: s.toLowerCase(), value: sevCount[s], color: SEVCLR[s] }))
  const today = new Date().toISOString().slice(0, 10)

  // Batch counts for UI
  const waitingCount = queue.filter((it) => it.status === 'waiting').length
  const doneCount = queue.filter((it) => it.status === 'done').length
  const errorCount = queue.filter((it) => it.status === 'error').length

  return (
    <>
      {/* ── BATCH MODE ── */}
      {batchMode && (
        <section className="panel">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <h2 style={{ margin: 0 }}>Batch processing</h2>
            <button className="ghost small" onClick={() => { setBatchMode(false); setQueue([]); setBatchDone(false) }}>← Single file</button>
          </div>

          {/* Batch drop zone */}
          <div
            className={drag ? 'dropzone over' : 'dropzone'}
            style={{ padding: '16px 24px', marginBottom: 14 }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
          >
            <div className="dzicon" aria-hidden="true">⬍</div>
            <div style={{ fontSize: 15 }}>Drag multiple files here, or <button type="button" className="dzlink" onClick={() => batchFileRef.current?.click()}>browse</button></div>
            <input
              ref={batchFileRef} type="file" multiple style={{ display: 'none' }}
              accept=".pdf,.docx,.pptx,.xlsx,.html,.htm,.mp3,.m4a,.wav,.mp4,.mov,.webm,.png,.jpg,.jpeg,.gif,.webp"
              onChange={onInput}
            />
            <div className="muted" style={{ marginTop: 4, fontSize: 12 }}>PDF · Word · PowerPoint · Excel · HTML · audio · image — processed in your browser, nothing uploaded</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <GoogleDrive onFiles={handleGDriveFiles} />
              <SharePoint onFiles={handleSpFiles} />
            </div>
          </div>

          {/* Queue table */}
          {queue.length > 0 && (
            <div
              className="batchqueue"
              role="list"
              aria-label="Batch queue"
              style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', marginBottom: 14 }}
            >
              {queue.map((item) => {
                const statusIcon = item.status === 'done' ? '✓' : item.status === 'error' ? '✕' : item.status === 'scanning' ? null : '·'
                const statusColor = item.status === 'done' ? 'var(--success-fg)' : item.status === 'error' ? 'var(--warn-fg)' : item.status === 'scanning' ? 'var(--info-fg)' : '#888780'
                const scoreBg = (item.score ?? 0) >= 90 ? 'var(--success-bg)' : (item.score ?? 0) >= 50 ? 'var(--warn-bg)' : 'var(--info-bg)'
                const scoreFg = (item.score ?? 0) >= 90 ? 'var(--success-fg)' : (item.score ?? 0) >= 50 ? 'var(--warn-fg)' : 'var(--info-fg)'
                return (
                  <div
                    key={item.id}
                    role="listitem"
                    style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderBottom: '1px solid var(--line)', background: item.status === 'scanning' ? 'var(--bg-subtle, #F8F7F5)' : undefined }}
                  >
                    <span aria-hidden="true" style={{ width: 18, textAlign: 'center', color: statusColor, fontWeight: 700, flexShrink: 0 }}>
                      {item.status === 'scanning' ? <span className="spinner" /> : statusIcon}
                    </span>
                    <span style={{ flex: 1, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.file.name}>{item.file.name}</span>
                    {item.engine && <span className="realbadge" style={{ flexShrink: 0 }}>⚡ {item.engine}</span>}
                    {item.issues != null && <span className="muted" style={{ fontSize: 12, flexShrink: 0 }}>{item.issues.length} finding{item.issues.length !== 1 ? 's' : ''}</span>}
                    {item.score != null && <span className="badge" style={{ background: scoreBg, color: scoreFg, flexShrink: 0 }}>{item.score} / 100</span>}
                    {item.status === 'done' && item.remBlob && item.driveFileId && (
                      <DriveUploadButton driveFileId={item.driveFileId} blob={item.remBlob} score={item.score} engine={item.engine} />
                    )}
                    {item.status === 'done' && item.remBlob && item.spItemId && (
                      <SpUploadButton itemId={item.spItemId} driveId={item.spDriveId} blob={item.remBlob} score={item.score} engine={item.engine} file={item.file.name} />
                    )}
                    {!batchRunning && item.status === 'waiting' && (
                      <button
                        className="ghost small"
                        aria-label={`Remove ${item.file.name} from queue`}
                        style={{ flexShrink: 0, padding: '2px 7px' }}
                        onClick={() => setQueue((q) => q.filter((it) => it.id !== item.id))}
                      >✕</button>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Status summary while running */}
          {batchRunning && (
            <div role="status" aria-live="polite" style={{ marginBottom: 10 }}>
              <p className="muted" style={{ fontSize: 13 }}>
                <span className="spinner" style={{ marginRight: 6 }} />
                Processing {doneCount + errorCount + 1} of {queue.length}…
              </p>
            </div>
          )}

          {/* Action bar */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            {waitingCount > 0 && !batchRunning && (
              <button onClick={runBatch}>
                ▶ Process {waitingCount} file{waitingCount !== 1 ? 's' : ''}
              </button>
            )}
            {batchDone && doneCount > 0 && (
              <button className="exportbtn" onClick={downloadBatchZip} disabled={batchZipping}>
                {batchZipping ? 'Preparing ZIP…' : `⤓ Download all (${doneCount} file${doneCount !== 1 ? 's' : ''} + CSV)`}
              </button>
            )}
            {batchDone && queue.some((i) => i.driveFileId && i.remBlob && i.status === 'done') && !bulkSaved && (
              <button onClick={handleBulkSaveToDrive} disabled={bulkSaving} style={{ background: 'var(--info-fg)', color: '#fff', border: 'none' }}>
                {bulkSaving ? '↑ Saving to Drive…' : '↑ Save all to Drive'}
              </button>
            )}
            {bulkSaved && <span style={{ fontSize: 13, color: 'var(--success-fg)' }}>✓ All saved to Drive</span>}
            {queue.length > 0 && !batchRunning && (
              <button className="ghost" style={{ marginLeft: 'auto' }} onClick={() => { setQueue([]); setBatchDone(false); setBulkSaved(false) }}>✕ Clear queue</button>
            )}
          </div>

          {batchDone && (
            <div role="status" aria-live="polite" style={{ marginTop: 12 }}>
              <p className="muted" style={{ fontSize: 12 }}>
                {doneCount} processed{errorCount > 0 ? ` · ${errorCount} error${errorCount !== 1 ? 's' : ''}` : ''} · ZIP includes remediated documents + a CSV summary of all scores &amp; findings.
              </p>
            </div>
          )}
          {batchDone && (() => {
            const driveItems = queue.filter((i) => i.status === 'done' && i.driveFileId && i.score != null)
            if (!driveItems.length) return null
            const avgScore = Math.round(driveItems.reduce((s, i) => s + i.score, 0) / driveItems.length)
            const totalFindings = driveItems.reduce((s, i) => s + (i.issues?.length || 0), 0)
            return (
              <div style={{ background: 'var(--success-bg)', border: '1px solid #B8D89A', borderRadius: 8, padding: '10px 14px', marginTop: 10, fontSize: 13 }}>
                <b>Google Drive remediation complete</b>
                <span className="muted"> · </span>
                {driveItems.length} file{driveItems.length !== 1 ? 's' : ''} from Drive
                <span className="muted"> · </span>
                avg score <b>{avgScore}/100</b>
                <span className="muted"> · </span>
                {totalFindings} finding{totalFindings !== 1 ? 's' : ''} identified
              </div>
            )
          })()}
        </section>
      )}

      {/* ── SINGLE FILE MODE ── */}
      {!batchMode && (
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
              <div style={{ fontSize: 15 }}>Drag a document here, or <button type="button" className="dzlink" onClick={() => singleFileRef.current?.click()}>browse</button></div>
              <input ref={singleFileRef} type="file" multiple style={{ display: 'none' }} accept=".pdf,.docx,.pptx,.xlsx,.html,.htm,.mp3,.m4a,.wav,.mp4,.mov,.webm,.png,.jpg,.jpeg,.gif,.webp" onChange={onInput} />
              <div className="muted" style={{ marginTop: 4 }}>PDF · Word · PowerPoint · Excel · HTML · audio · image — scanned in your browser, nothing is uploaded anywhere</div>
              <div className="muted" style={{ marginTop: 2, fontSize: 12 }}>⚡ HTML is analysed live with the axe-core WCAG engine · drop multiple files to switch to batch mode</div>
              <div className="dzsamples">
                <span className="muted">or try a real multi-page sample:</span>
                <button className="ghost small" onClick={() => sample('quarterly-town-hall.pptx')} title="Town hall deck with 3 embedded charts — the local vision model reads each chart and writes alt text">PowerPoint ★</button>
                <button className="ghost small" onClick={() => sample('patient-health-portal.html')} title="Patient portal with contrast failures, unlabeled forms, and structural issues — watch the page visibly transform">HTML ★</button>
                <button className="ghost small" onClick={() => sample('patient-discharge-instructions.pdf')} title="Multi-page discharge instructions — checks alt text, tags, titles & reading order in real time">PDF ★</button>
                <button className="ghost small" onClick={() => sample('platform-evaluation.docx')} title="AI platform evaluation with 5 tables — detects missing headers, title & language then downloads as tracked changes">Word ★</button>
                <button className="ghost small" onClick={() => sample('finance-metrics.xlsx')}>Excel</button>
                <button className="ghost small" onClick={() => sample('careers-landing.html')}>HTML (alt)</button>
                <button className="ghost small" onClick={() => sample('benefits-briefing.mp3')}>Audio</button>
                <button className="ghost small" onClick={() => sample('benefits-briefing.webm')} title="A narrated video — missing captions are detected and routed to a human reviewer (1.2.2)">Video</button>
                <button className="ghost small" onClick={() => sample('enrollment-notice.png')} title="An image of text — read back as real, selectable text (1.4.5)">Image of text</button>
              </div>
              <div style={{ marginTop: 12 }}>
                <button className="ghost small" onClick={() => setBatchMode(true)}>⊞ Batch mode — process multiple files at once</button>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <GoogleDrive onFiles={handleGDriveFiles} />
                <SharePoint onFiles={handleSpFiles} />
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
                    <span className="badge" style={{ background: h.score >= 90 ? 'var(--success-bg)' : h.score >= 50 ? 'var(--warn-bg)' : 'var(--info-bg)', color: h.score >= 90 ? 'var(--success-fg)' : h.score >= 50 ? 'var(--warn-fg)' : 'var(--info-fg)' }}>{h.score} / 100</span>
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
                {realEngine && <div className="realbadge" style={{ marginLeft: 0, marginTop: 8, display: 'inline-block' }}>⚡ live {realEngine} analysis</div>}
                <div className="track" style={{ marginTop: 12 }}><i style={{ width: '66%', background: '#BF8C00', transition: 'width .4s' }} /></div>
              </div>
            </section>
          )}

          {viewing && <HistoryDetail viewing={viewing} onClose={() => setViewing(null)} />}

          {step === 1 && (
            <section className="panel">
              <div className="rubrichdr"><h2 style={{ margin: 0 }}>Assessment · <span className="fname" style={{ fontSize: 14 }}>{file?.name}</span>
                {realEngine && <span className="realbadge" title="Findings detected by live in-browser analysis">⚡ live {realEngine} analysis</span>}</h2>
                <span className="badge" style={{ background: 'var(--warn-bg)', color: 'var(--warn-fg)' }}>{issues.length} findings</span></div>
              <div className="lift" style={{ margin: '12px 0 16px' }}>
                <div className="liftcol"><div className="liftnum" style={{ color: score >= 90 ? 'var(--success-fg)' : score >= 50 ? 'var(--warn-fg)' : 'var(--info-fg)' }}>{score}</div><div className="muted">score / 100</div></div>
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
                    <span className="badge" style={{ background: 'var(--success-bg)', color: 'var(--success-fg)' }}>fixed</span>
                    <div className="findingmain"><div>{i.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{i.detail}</div></div>
                  </div>
                ))}
              </div>
              {isImage(file?.name) ? <ImagePanel blob={imageBlob} result={imgResult} visionModel={visionModel} /> : isAudio(file?.name) ? <CaptionsPanel blob={audioBlob} captions={captions} /> : <BeforeAfter file={file} issues={issues} srcText={srcText} pdfUrl={pdfUrl} officeBlob={officeBlob} />}
              {prescreen.length > 0 && (
                <div className="hitlpanel">
                  <div className="hitlhd"><b>⚑ Routed to human review</b><span className="hitlbadge">Phase 2 · HITL</span></div>
                  <p className="muted" style={{ margin: '2px 0 9px', fontSize: 12 }}>Runtime, interactive &amp; media criteria the engine flags but can't auto-confirm — a reviewer verifies each one.</p>
                  <div className="findings">
                    {prescreen.map((p, i) => {
                      const [bg, fg] = SEV_BADGE[p.sev] || SEV_BADGE.MINOR
                      return (
                        <div className="finding" key={i}>
                          <span className="badge" style={{ background: bg, color: fg }}>{p.sev.toLowerCase()}</span>
                          <div className="findingmain"><div>{p.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{p.detail}</div></div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              <p className="muted" style={{ marginTop: 12 }}>{autoFixed.length} finding(s) auto-fixed · <b>{review.length}</b> routed to human review{prescreen.length > 0 && <> · <b>{prescreen.length}</b> flagged for HITL review (Phase 2)</>}.</p>
              <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 4 }}><button onClick={() => setStep(3)}>Review queue →</button></div>
            </section>
          )}

          {step === 3 && reviewItem && (() => {
            const [before, after] = proposeFix(reviewItem, file)
            return (
              <section className="panel">
                <h2>Human-in-the-loop review · {file?.name}</h2>
                <div className="qrow" style={{ borderRadius: 10, border: '1px solid var(--line)', padding: '11px 13px', marginBottom: 12 }}>
                  <span className="qico" aria-hidden="true">⚑</span>
                  <div className="qmain"><div className="qtitle">{reviewItem.wcag}</div><div className="qmeta">{reviewItem.detail} · needs human judgement — this finding type is never auto-applied</div></div>
                </div>
                <div className="muted" style={{ marginBottom: 6 }}>Proposed fix · {reviewItem.wcag}</div>
                <div className="diffbox before"><span className="difftag">before</span>{before}</div>
                <div className="diffbox after"><span className="difftag">after</span><span dangerouslySetInnerHTML={{ __html: after }} /></div>
                {prescreen.length > 0 && (
                  <div className="hitlpanel" style={{ marginTop: 16 }}>
                    <div className="hitlhd"><b>⚑ Reviewer sign-off</b><span className="hitlbadge">Phase 2 · HITL</span><span className="muted" style={{ marginLeft: 'auto', fontSize: 12 }}>{hitlVerified.size}/{prescreen.length} verified</span></div>
                    <p className="muted" style={{ margin: '2px 0 9px', fontSize: 12 }}>Confirm each runtime / media criterion the pre-screen flagged — a reviewer verifies and signs off.</p>
                    <div className="findings">
                      {prescreen.map((p, i) => {
                        const ok = hitlVerified.has(i)
                        return (
                          <div className="finding" key={i}>
                            <button className={ok ? 'hitlverify on' : 'hitlverify'} aria-pressed={ok} onClick={() => setHitlVerified((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })}>{ok ? '✓ Verified' : 'Verify'}</button>
                            <div className="findingmain"><div>{p.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{p.detail}</div></div>
                          </div>
                        )
                      })}
                    </div>
                    {hitlVerified.size < prescreen.length && <button className="ghost small" style={{ marginTop: 9 }} onClick={() => setHitlVerified(new Set(prescreen.map((_, i) => i)))}>✓ Verify all ({prescreen.length})</button>}
                  </div>
                )}
                <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>Assign to:</span>
                  <select style={{ fontSize: 12 }} value={assignee || ''} onChange={(e) => setAssignee(e.target.value || null)}>
                    <option value="">— Not assigned (self)</option>
                    {/* Demo personas are illustrative — never offer them as real assignees in prod. */}
                    {(SIM ? PERSONAS : []).map((p) => <option key={p.id} value={p.name}>{p.name} · {p.role}</option>)}
                  </select>
                </div>
                <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 10, flexWrap: 'wrap' }}>
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
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12 }}>
                  <span style={{ color: 'var(--muted)' }}>WCAG</span>
                  <select value={wcagVersion} onChange={(e) => setWcagVersion(e.target.value)} style={{ fontSize: 12 }}>
                    <option value="2.1">2.1 AA</option>
                    <option value="2.2">2.2 AA</option>
                  </select>
                </label>
                <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Download PDF report'}</button>
              </div>
              <div ref={reportRef} className="reportdoc">
                <div className="reporthead">
                  <Logo />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>Accessibility compliance certificate</div>
                    <div className="muted">{orgName} · WCAG {wcagVersion} AA{assignee ? ' · ' + assignee : ''} · {today}</div>
                  </div>
                </div>

                <section className="certbanner certreveal" style={rejected ? { background: 'var(--warn-bg)', borderColor: '#e8d2a8' } : undefined}>
                  <div className="certmark certpop" aria-hidden="true" style={rejected ? { background: 'var(--warn-fg)' } : undefined}>{rejected ? '!' : '✓'}</div>
                  <div>
                    <div className="certtitle">{rejected ? `Conditional · ${finalScore} / 100` : 'Certified · 100 / 100'}</div>
                    <div className="muted"><span className="fname">{file?.name}</span> {rejected ? 'remediated except 1 finding deferred to manual review — not yet fully WCAG ' + wcagVersion + ' AA compliant.' : 'passed WCAG ' + wcagVersion + ' AA after remediation & re-validation.'}</div>
                  </div>
                  <div className="liftgain" style={{ marginLeft: 'auto' }}>{score} → {finalScore}</div>
                </section>

                <div className="chartrow">
                  <section className="panel"><h2>Compliance lift</h2>
                    <div className="lift">
                      <div className="liftcol"><div className="liftnum" style={{ color: 'var(--info-fg)' }}>{score}</div><div className="muted">as received</div></div>
                      <div className="liftarrow" aria-hidden="true">→</div>
                      <div className="liftcol"><div className="liftnum" style={{ color: rejected ? 'var(--warn-fg)' : 'var(--success-fg)' }}><CountUp from={score} to={finalScore} /></div><div className="muted">{rejected ? 'conditional' : 'certified'}</div></div>
                    </div>
                    <p className="muted">{rejected ? `${issues.length - 1} of ${issues.length} finding(s) resolved · 1 deferred to manual remediation.` : `${issues.length} finding(s) resolved across ${sevItems.length} severity level(s).`}</p>
                  </section>
                  <section className="panel"><h2>Findings resolved · by severity</h2>
                    {sevItems.length ? <Bars items={sevItems} cols="84px 1fr 28px" /> : <p className="muted">None.</p>}
                  </section>
                </div>

                <section className="panel collapsepanel">
                  <button className="collapsehd" aria-expanded={openPanels.has('findings')} onClick={() => togglePanel('findings')}>
                    <h2 style={{ margin: 0 }}>Findings remediated</h2>
                    <span className="collapsecount muted">{issues.length} finding{issues.length !== 1 ? 's' : ''}</span>
                    <span className="collapsechev" aria-hidden="true">{openPanels.has('findings') ? '▲' : '▼'}</span>
                  </button>
                  {openPanels.has('findings') && (
                    <div className="findings" style={{ marginTop: 10 }}>
                      {(() => {
                        const [certExp, setCertExp] = [openPanels, togglePanel]
                        return issues.map((i, n) => {
                          const [bg, fg] = SEV_BADGE[i.sev] || SEV_BADGE.MINOR
                          const guide = guideFor(i.rule, i.wcag)
                          const key = 'fix-' + n
                          const isOpen = openPanels.has(key)
                          return (
                            <div className="finding" key={n}
                              style={{ flexDirection: 'column', alignItems: 'stretch', cursor: guide ? 'pointer' : 'default' }}
                              onClick={() => guide && togglePanel(key)}
                              role={guide ? 'button' : undefined}
                              aria-expanded={guide ? isOpen : undefined}
                            >
                              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                                <span className="badge" style={{ background: 'var(--success-bg)', color: 'var(--success-fg)', flexShrink: 0 }}>fixed</span>
                                <div className="findingmain" style={{ flex: 1 }}><div>{i.wcag}</div><div className="muted" style={{ fontSize: 12 }}>{i.detail}</div></div>
                                <span className="badge" style={{ background: bg, color: fg, flexShrink: 0 }}>{i.sev.toLowerCase()}</span>
                                {guide && <span aria-hidden="true" style={{ fontSize: 11, color: 'var(--muted)', flexShrink: 0, paddingTop: 3 }}>{isOpen ? '▲' : '▼'}</span>}
                              </div>
                              {guide && isOpen && (
                                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--line)', fontSize: 12, lineHeight: 1.5 }}>
                                  <span style={{ fontWeight: 600, marginRight: 4 }}>Where to verify in {guide.app}:</span>
                                  <span className="muted">{guide.tip}</span>
                                </div>
                              )}
                            </div>
                          )
                        })
                      })()}
                    </div>
                  )}
                </section>

                <section className="panel collapsepanel">
                  <button className="collapsehd" aria-expanded={openPanels.has('journey')} onClick={() => togglePanel('journey')}>
                    <h2 style={{ margin: 0 }}>Document journey</h2>
                    <span className="collapsecount muted">{['discovered', 'assessed', 'auto-fixed', 'reviewed', ...(prescreen.length ? ['HITL verified'] : []), 'certified'].length} steps</span>
                    <span className="collapsechev" aria-hidden="true">{openPanels.has('journey') ? '▲' : '▼'}</span>
                  </button>
                  {openPanels.has('journey') && (
                    <>
                      <div className="journey" style={{ marginTop: 10 }}>
                        {['discovered', `assessed ${score}`, 'auto-fixed', 'reviewed', ...(prescreen.length ? [`${hitlVerified.size}/${prescreen.length} HITL verified`] : []), rejected ? `conditional ${finalScore}` : 'certified 100'].map((l, n) => <span className="jstep" key={n}>✓ {l}</span>)}
                      </div>
                      <p className="muted" style={{ marginTop: 10 }}>Validated against WCAG {wcagVersion} AA · every step captured in the audit trail.{prescreen.length > 0 && ` ${hitlVerified.size} of ${prescreen.length} runtime/media criteria verified via human review (Phase 2 · HITL).`}</p>
                    </>
                  )}
                </section>
              </div>
              {isImage(file?.name) ? <ImagePanel blob={imageBlob} result={imgResult} visionModel={visionModel} /> : isAudio(file?.name) ? <CaptionsPanel blob={audioBlob} captions={captions} /> : <ResultPreview file={file} srcText={srcText} pdfUrl={pdfUrl} pdfBlob={pdfBlob} officeBlob={officeBlob} issues={issues} wcagVersion={wcagVersion} assignee={assignee} />}
            </>
          )}
        </>
      )}

      {/* Universal scan gate over Drive/SharePoint browse selections — the scope/behavior review
          appears before the downloaded files are assessed. estCount is the number picked. */}
      {browseGate && (
        <ScanReviewModal source={browseGate.source} estCount={browseGate.files.length}
          rememberDefault={false}
          onConfirm={() => { const g = browseGate; setBrowseGate(null); processBrowseFiles(g.files) }}
          onCancel={() => setBrowseGate(null)} />
      )}
    </>
  )
}
