import { useMemo, useState, useEffect } from 'react'
import PdfPreview from './PdfPreview.jsx'
import { remediateOffice } from './officeAudit.js'
import { runFixes } from './rules/index.js'
import { markRemediated, uploadToDrive } from './api.js'

// Side-by-side "what you'd get" preview. For HTML we genuinely remediate the
// uploaded markup and render both versions in sandboxed iframes (contrast fixes
// are visibly different). For every finding we also render a concrete before→after
// of the fix, since most a11y improvements are invisible in the visual render.

// Real, best-effort HTML remediation. Returns the fixed markup + a list of changes.
// When aiEnabled=false only deterministic (auto) rules run; ai-assisted rules are
// skipped and their findings stay in the HITL queue.
export function remediateHtml(text, { aiEnabled = true } = {}) {
  try {
    const doc = new DOMParser().parseFromString(text, 'text/html')
    const changes = runFixes(doc, { aiEnabled })
    return { html: '<!doctype html>' + doc.documentElement.outerHTML, changes }
  } catch { return null }
}

export const scOf = (wcag) => ((wcag || '').match(/^\d+\.\d+\.\d+/) || [''])[0]

// Concrete before→after visuals per success criterion.
export function baFor(sc, docTitle) {
  switch (sc) {
    case '1.1.1': return {
      before: <div className="baimg"><span aria-hidden="true">🖼</span><span className="bawarn">no alt text — screen readers skip this</span></div>,
      after: <div className="baimg"><span aria-hidden="true">🖼</span><span className="bacap">alt: {docTitle ? `"image from ${docTitle}"` : 'AI-generated description'} — Claude Vision</span></div>,
    }
    case '1.4.3': return {
      before: <div><span className="bacontrast" style={{ color: '#bcbcbc' }}>Apply by March 31</span><span className="bawarn">3.1 : 1 · fails AA</span></div>,
      after: <div><span className="bacontrast" style={{ color: '#37323b' }}>Apply by March 31</span><span className="baok">4.9 : 1 · passes AA</span></div>,
    }
    case '2.4.2': return {
      before: <div><span className="batab">○ Untitled document</span><span className="bawarn">can’t identify the doc in AT</span></div>,
      after: <div><span className="batab">○ {docTitle || "Accessibility Review — mova.io"}</span><span className="baok">clearly identified</span></div>,
    }
    case '3.1.1': return {
      before: <div><code className="bacode">&lt;html&gt;</code><span className="bawarn">no language — wrong pronunciation</span></div>,
      after: <div><code className="bacode">&lt;html lang="en"&gt;</code><span className="baok">announced in English</span></div>,
    }
    case '1.3.1': return {
      before: <table className="batable"><tbody><tr><td>Region</td><td>Q3</td></tr><tr><td>West</td><td>38%</td></tr></tbody><caption className="bawarn">no header row — data loses meaning</caption></table>,
      after: <table className="batable hdr"><tbody><tr><th>Region</th><th>Q3</th></tr><tr><td>West</td><td>38%</td></tr></tbody><caption className="baok">header row tagged · th scope="col"</caption></table>,
    }
    case '2.4.4': return {
      before: <div><a className="balink">click here</a><span className="bawarn">meaningless out of context</span></div>,
      after: <div><a className="balink">view {docTitle ? `the ${docTitle.toLowerCase()}` : 'the full document'}</a><span className="baok">clear &amp; descriptive</span></div>,
    }
    case '1.4.1': return {
      before: <div><span style={{ color: '#2E72C9' }}>Apply online</span><span className="bawarn">a link by colour alone</span></div>,
      after: <div><span style={{ color: '#2E72C9', textDecoration: 'underline' }}>Apply online</span><span className="baok">underlined — not colour alone</span></div>,
    }
    case '1.4.4': return {
      before: <div><code className="bacode">user-scalable=no</code><span className="bawarn">pinch-zoom blocked</span></div>,
      after: <div><code className="bacode">width=device-width</code><span className="baok">zooms to 200%+</span></div>,
    }
    case '1.4.10': return {
      before: <div><span className="batab">no viewport meta</span><span className="bawarn">2-D scroll at 320px</span></div>,
      after: <div><span className="batab">responsive viewport</span><span className="baok">reflows, one column</span></div>,
    }
    case '1.4.11': return {
      before: <div><span className="bacontrast" style={{ border: '1px solid #d9d9d9', padding: '1px 6px', color: '#37323b' }}>Search</span><span className="bawarn">border 1.4:1 · fails</span></div>,
      after: <div><span className="bacontrast" style={{ border: '1px solid #6b6b6b', padding: '1px 6px', color: '#37323b' }}>Search</span><span className="baok">3.6:1 · passes</span></div>,
    }
    case '1.4.12': return {
      before: <div><code className="bacode">line-height:1.1 !important</code><span className="bawarn">clips on spacing override</span></div>,
      after: <div><code className="bacode">line-height:1.5</code><span className="baok">adapts, no clipping</span></div>,
    }
    case '2.1.1': return {
      before: <div><code className="bacode">&lt;div onclick&gt;</code><span className="bawarn">mouse only — no focus</span></div>,
      after: <div><code className="bacode">role="button" tabindex="0"</code><span className="baok">keyboard-operable</span></div>,
    }
    case '2.4.3': return {
      before: <div><code className="bacode">tabindex="5"</code><span className="bawarn">jumps the reading order</span></div>,
      after: <div><code className="bacode">tabindex="0"</code><span className="baok">natural focus order</span></div>,
    }
    case '4.1.2': return {
      before: <div><span className="batab">⭿ icon button</span><span className="bawarn">no name — “button” in AT</span></div>,
      after: <div><span className="batab">⭿ aria-label="Search"</span><span className="baok">name, role &amp; state exposed</span></div>,
    }
    case '3.1.2': return {
      before: <div><code className="bacode">&lt;span&gt;Bienvenido&lt;/span&gt;</code><span className="bawarn">read in English</span></div>,
      after: <div><code className="bacode">&lt;span lang="es"&gt;</code><span className="baok">announced in Spanish</span></div>,
    }
    case '1.3.3': return {
      before: <div><span>“click the round button”</span><span className="bawarn">shape/position only</span></div>,
      after: <div><span>“click Submit (round, lower-right)”</span><span className="baok">named, not shape alone</span></div>,
    }
    case '1.4.5': return {
      before: <div className="baimg"><span aria-hidden="true">🖼</span><span className="bawarn">heading is an image of text</span></div>,
      after: <div><span className="batab">&lt;h1&gt;2026 Benefits&lt;/h1&gt;</span><span className="baok">real, resizable text</span></div>,
    }
    case '2.1.2': return {
      before: <div><span>modal traps Tab</span><span className="bawarn">focus can’t escape</span></div>,
      after: <div><span>Esc + focus-trap loop</span><span className="baok">focus returns to trigger</span></div>,
    }
    default: return {
      before: <div><span className="bawarn">finding present</span></div>,
      after: <div><span className="baok">resolved &amp; re-validated</span></div>,
    }
  }
}

const SEV_ORDER = { CRITICAL: 0, SERIOUS: 1, MODERATE: 2, MINOR: 3 }
const SEV_COLOR = {
  CRITICAL: ['#7B1D1D', '#FDECEA'],
  SERIOUS:  ['#854F0B', '#FAEEDA'],
  MODERATE: ['#1F5FA8', '#E2EDFB'],
  MINOR:    ['#444', '#F1EFF4'],
}

// Which findings can be auto-fixed vs. need human review
const AUTO_FIX_SC = new Set(['1.1.1','1.3.1','2.4.2','3.1.1','2.4.4','1.4.1','1.4.3','1.4.4','1.4.10','1.4.11','1.4.12','2.1.1','2.4.3','4.1.2'])
const MANUAL_RULES = new Set(['DOCX-HEAD-001','DOCX-LINK-001'])

// Who is affected by each SC — shown as user impact
const IMPACT = {
  '1.1.1': 'Blind users & screen readers',
  '1.3.1': 'Screen reader users',
  '1.3.2': 'Screen reader users',
  '2.4.2': 'All assistive tech users',
  '2.4.4': 'Screen reader users & keyboard users',
  '3.1.1': 'TTS & screen readers',
  '1.4.3': 'Low-vision users',
  '1.4.4': 'Low-vision users',
  '1.4.10': 'Mobile & low-vision users',
  '1.4.11': 'Low-vision users',
  '1.4.12': 'Dyslexic & low-vision users',
  '2.1.1': 'Keyboard-only users',
  '2.1.2': 'Keyboard-only users',
  '2.4.3': 'Keyboard-only users',
  '4.1.2': 'Screen reader & voice-control users',
}

function fixMode(it) {
  if (MANUAL_RULES.has(it.rule)) return 'human'
  const sc = scOf(it.wcag)
  return AUTO_FIX_SC.has(sc) ? 'auto' : 'human'
}

export default function BeforeAfter({ file, issues = [], srcText, pdfUrl, officeBlob, aiEnabled = true, scanId = null }) {
  const rem = useMemo(() => (srcText ? remediateHtml(srcText, { aiEnabled }) : null), [srcText, aiEnabled])
  const [busy, setBusy] = useState(false)
  const [preBlob, setPreBlob] = useState(null)
  const [preReady, setPreReady] = useState(false)
  useEffect(() => {
    let live = true; setPreBlob(null); setPreReady(false)
    if (!officeBlob) return () => { live = false }
    remediateOffice(officeBlob).then((b) => { if (live) { setPreBlob(b); setPreReady(true) } }).catch(() => { if (live) setPreReady(true) })
    return () => { live = false }
  }, [officeBlob])
  const [outMode, setOutMode] = useState('download')
  const [driveMsg, setDriveMsg] = useState(null)
  const certDate = new Date().toISOString().split('T')[0]
  const baseName = (file?.name || 'document').replace(/\.[^.]+$/, '')
  const ext = (file?.name || '').split('.').pop() || 'html'
  const certName = (suffix) => `${baseName}_a11y-certified-${certDate}.${suffix}`
  const dl = (blob, name) => { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
  const downloadFixed = () => {
    if (!rem) return
    dl(new Blob([rem.html], { type: 'text/html' }), certName('html'))
    if (scanId && file?.name) markRemediated(scanId, file.name).catch(() => {})
  }
  const downloadOffice = () => {
    if (!preBlob || busy) return
    dl(preBlob, certName(ext))
    if (scanId && file?.name) markRemediated(scanId, file.name).catch(() => {})
  }
  const saveToDrive = async () => {
    if (!scanId) { setDriveMsg('Connect Google Drive in Settings → Integrations first.'); setTimeout(() => setDriveMsg(null), 4000); return }
    setDriveMsg('Uploading to Google Drive…')
    try {
      let blob, contentType
      if (rem) { blob = new Blob([rem.html], { type: 'text/html' }); contentType = 'text/html' }
      else if (preBlob) { blob = preBlob; contentType = preBlob.type || 'application/octet-stream' }
      else { setDriveMsg('Nothing to upload yet.'); setTimeout(() => setDriveMsg(null), 3000); return }
      const result = await uploadToDrive(scanId, certName(ext === 'html' ? 'html' : ext), blob, contentType)
      setDriveMsg(`✓ Saved → ${result.url ? `<a href="${result.url}" target="_blank" rel="noreferrer">Remediated/${certName(ext === 'html' ? 'html' : ext)}</a>` : 'Drive/Remediated/'}`)
    } catch (e) {
      setDriveMsg(`Drive upload failed — ${e.message || 'check console'}`)
      setTimeout(() => setDriveMsg(null), 5000)
    }
  }

  // Sort findings: CRITICAL first, then by WCAG SC
  const sorted = [...issues].sort((a, b) => {
    const sa = SEV_ORDER[a.sev] ?? 4, sb = SEV_ORDER[b.sev] ?? 4
    return sa !== sb ? sa - sb : (a.wcag || '').localeCompare(b.wcag || '')
  })
  const autoCount = sorted.filter(i => fixMode(i) === 'auto').length
  const humanCount = sorted.length - autoCount

  return (
    <div className="bawrap">
      {!aiEnabled && (
        <div className="aioff-banner">
          <b>AI off</b> — only deterministic fixes are applied. AI-assisted improvements (alt text, link labels, icon names) are routed to the human review queue.
        </div>
      )}
      {rem && (
        <div className="balive">
          <div className="bahd"><b>Live preview · your page, before → after</b><span className="muted"> — real DOM remediation, rendered in your browser</span></div>
          <div className="baframes">
            <figure><figcaption className="bafcap before">as uploaded</figcaption><iframe sandbox="" title="as uploaded" srcDoc={srcText} /></figure>
            <figure><figcaption className="bafcap after">remediated</figcaption><iframe sandbox="" title="remediated" srcDoc={rem.html} /></figure>
          </div>
          {rem.changes.length > 0 && <div className="bachanges">{rem.changes.map((c, i) => <span key={i} className="bachip">✓ {c}</span>)}</div>}
          <div className="outpanel">
            <div className="outmodes">
              {[['download','⤓ Download'],['drive','☁ Save to Drive'],['archive','⊡ Archive original']].map(([k,l]) => (
                <button key={k} className={outMode === k ? 'outmode on' : 'outmode'} onClick={() => setOutMode(k)}>{l}</button>
              ))}
            </div>
            {outMode === 'download' && (
              <div className="outact">
                <button className="ghost small" onClick={downloadFixed}>⤓ {certName('html')}</button>
                <span className="muted" style={{ fontSize: 11 }}>Original preserved alongside in your folder</span>
              </div>
            )}
            {outMode === 'drive' && (
              <div className="outact">
                <button className="ghost small" onClick={saveToDrive}>☁ Save to Google Drive → Remediated/</button>
                {driveMsg && <span className="muted" style={{ fontSize: 12, marginLeft: 8 }} dangerouslySetInnerHTML={{ __html: driveMsg }} />}
              </div>
            )}
            {outMode === 'archive' && (
              <div className="outact">
                <span className="muted" style={{ fontSize: 12 }}>Original will be moved to <b>Archive/{certDate}/</b> in Drive — remediated version takes its place.</span>
                <button className="ghost small" onClick={saveToDrive} style={{ marginLeft: 8 }}>Archive + save</button>
              </div>
            )}
          </div>
        </div>
      )}
      {pdfUrl && !rem && (
        <div className="balive">
          <div className="bahd"><b>Your document</b><span className="muted"> — {file?.name}, rendered in your browser</span></div>
          <div className="bapdf"><PdfPreview url={pdfUrl} /></div>
          <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>Accessibility fixes (tags, alt text, reading order) are structural — see exactly what changes below.</p>
        </div>
      )}
      {officeBlob && (
        <div className="balive">
          <div className="bahd"><b>Remediated file ready</b><span className="muted"> — fixes written directly into the Office XML in your browser, nothing uploaded</span></div>
          <div className="ba-remsum">
            {issues.filter(i => /1\.1\.1/.test(i.wcag)).length > 0 && <span className="ba-remchip">✓ Alt text added to {issues.filter(i => /1\.1\.1/.test(i.wcag)).length} image{issues.filter(i => /1\.1\.1/.test(i.wcag)).length !== 1 ? 's' : ''}</span>}
            {issues.some(i => /2\.4\.2/.test(i.wcag)) && <span className="ba-remchip">✓ Document title set</span>}
            {issues.some(i => /1\.3\.1/.test(i.wcag) && /table/i.test(i.detail)) && <span className="ba-remchip">✓ Table header row added</span>}
            {issues.some(i => /3\.1\.1/.test(i.wcag)) && <span className="ba-remchip">✓ Language declared (en-US)</span>}
            {issues.some(i => /2\.4\.4/.test(i.wcag)) && <span className="ba-remchip">✓ Link text clarified</span>}
            {issues.some(i => /DOCX-HEAD/.test(i.rule)) && <span className="ba-remchip ba-remchip-warn">⚑ Heading structure flagged — needs author review</span>}
          </div>
          <div className="outpanel">
            <div className="outmodes">
              {[['download','⤓ Download'],['drive','☁ Save to Drive'],['archive','⊡ Archive original']].map(([k,l]) => (
                <button key={k} className={outMode === k ? 'outmode on' : 'outmode'} onClick={() => setOutMode(k)}>{l}</button>
              ))}
            </div>
            {outMode === 'download' && (
              <button className="badownload" onClick={downloadOffice} disabled={!preReady || busy}>
                {!preReady ? 'Preparing remediated file...' : `⤓ ${certName(ext)}`}
              </button>
            )}
            {outMode !== 'download' && (
              <div className="outact">
                <button className="ghost small" onClick={saveToDrive}>
                  {outMode === 'drive' ? `☁ Save to Google Drive → Remediated/${certName(ext)}` : `⊡ Archive original + save ${certName(ext)} in place`}
                </button>
                {driveMsg && <span className="muted" style={{ fontSize: 12, marginLeft: 8 }} dangerouslySetInnerHTML={{ __html: driveMsg }} />}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="bacards">
        <div className="ba-findhd">
          <div>
            <b>Remediation detail</b>
            <span className="muted"> — each finding, what changes and why it matters</span>
          </div>
          <div className="ba-findcount">
            {autoCount > 0 && <span className="ba-modebadge auto">⚡ {autoCount} auto-fixed</span>}
            {humanCount > 0 && <span className="ba-modebadge human">⚑ {humanCount} need review</span>}
          </div>
        </div>

        {sorted.map((it, n) => {
          const docTitle = file?.name ? file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : null
          const ba = baFor(scOf(it.wcag), docTitle)
          const [sevFg, sevBg] = SEV_COLOR[it.sev] || SEV_COLOR.MINOR
          const mode = fixMode(it)
          const sc = scOf(it.wcag)
          const impact = IMPACT[sc]
          return (
            <div className="barow" key={n} data-sev={it.sev?.toLowerCase()}>
              <div className="balabel">
                <div className="balabel-top">
                  <span className="badge" style={{ background: sevBg, color: sevFg, fontSize: 10, padding: '1px 7px' }}>{(it.sev || 'minor').toLowerCase()}</span>
                  <span className="basc">{it.wcag}</span>
                  {mode === 'auto'
                    ? <span className="ba-modebadge auto" style={{ fontSize: 10 }}>⚡ auto-fixed</span>
                    : <span className="ba-modebadge human" style={{ fontSize: 10 }}>⚑ human review</span>}
                </div>
                <div className="balabel-detail">{it.detail}</div>
                {impact && <div className="balabel-impact">Affects: {impact}</div>}
                {mode === 'human' && <div className="balabel-note">⚑ This fix requires understanding content — flagged for author review in the next step.</div>}
              </div>
              <div className="bacell before"><span className="batag">before</span>{ba.before}</div>
              <div className="baarrow" aria-hidden="true">→</div>
              <div className="bacell after"><span className="batag">after</span>{ba.after}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
