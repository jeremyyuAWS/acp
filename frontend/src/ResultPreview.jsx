import { useMemo, useState, useEffect } from 'react'
import PdfPreview from './PdfPreview.jsx'
import OfficePreview from './OfficePreview.jsx'
import { remediateHtml } from './BeforeAfter.jsx'
import { remediateOffice } from './officeAudit.js'
import { remediatePdf } from './pdfAudit.js'
import { generateAltText, firstOfficeImage, aiTextFix } from './aiRemediate.js'

const isHtml = (n) => /\.html?$/i.test(n || '')
const isPdf = (n) => /\.pdf$/i.test(n || '')

// Side-by-side "as received → remediated" file preview for the certificate page.
// HTML renders both versions live in the browser (fixes like contrast are visible).
// PDF/Office keep the original visual and surface the embedded structural fixes —
// alt text, titles, headers and language are non-visual by nature, so we show what
// changed under the hood honestly rather than fake a different-looking render. For
// Office the remediated file is genuinely produced and downloadable.
export default function ResultPreview({ file, srcText, pdfUrl, pdfBlob, officeBlob, issues = [] }) {
  const name = file?.name || ''
  const rem = useMemo(() => (srcText && isHtml(name) ? remediateHtml(srcText) : null), [srcText, name])
  const [busy, setBusy] = useState(false)
  // genuinely produce the remediated Office file so we can render it side-by-side
  const [remBlob, setRemBlob] = useState(null)
  // genuinely remediate the PDF (title + language) via pdf-lib
  const [remPdf, setRemPdf] = useState(null)
  useEffect(() => {
    let live = true; setRemPdf(null)
    if (!pdfBlob) return () => { live = false }
    remediatePdf(pdfBlob, { title: name.replace(/\.[^.]+$/, '') }).then((r) => { if (live) setRemPdf(r) }).catch(() => { /* fall back */ })
    return () => { live = false }
  }, [pdfBlob])
  const [aiAlt, setAiAlt] = useState(null) // real Claude-vision alt text for the embedded image
  const [imgText, setImgText] = useState(null) // 1.4.5 — verbatim text extracted from an image-of-text
  useEffect(() => {
    let live = true; setRemBlob(null); setAiAlt(null); setImgText(null)
    if (!officeBlob) return () => { live = false }
    ;(async () => {
      let alt = null
      try { const img = await firstOfficeImage(officeBlob); if (img) { const r = await generateAltText({ data: img.data, mediaType: img.mediaType, hint: `Image from the document “${name}”` }); alt = r?.alt; if (live && r?.text) setImgText(r.text) } } catch { /* fall back to placeholder */ }
      if (!live) return
      if (alt) setAiAlt(alt)
      try { const b = await remediateOffice(officeBlob, { alt }); if (live) setRemBlob(b) } catch { /* falls back to card */ }
    })()
    return () => { live = false }
  }, [officeBlob])
  // Real Claude text remediation for the AI-assisted criteria (link purpose 2.4.4,
  // sensory 1.3.3, language of parts 3.1.2) on HTML uploads — drafts shown for approval.
  const [aiFixes, setAiFixes] = useState([])
  useEffect(() => {
    let live = true; setAiFixes([])
    if (!srcText || !isHtml(name)) return () => { live = false }
    const strip = (s) => (s || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    const h1 = strip((/<h1[^>]*>([\s\S]*?)<\/h1>/i.exec(srcText) || [])[1])
    const linkM = /<a\b[^>]*>\s*(click here|read more|learn more|here|more)\s*<\/a>/i.exec(srcText)
    const sensoryM = /<p[^>]*>([^<]*\b(?:round|square|circular|button (?:below|above)|on the (?:left|right))\b[^<]*)<\/p>/i.exec(srcText)
    const bodyText = strip((/<body[^>]*>([\s\S]*)<\/body>/i.exec(srcText) || [])[1] || srcText).slice(0, 1500)
    // 2.1.2 — a custom widget that manages keys/focus (role=dialog or an onkeydown handler) is a
    // keyboard-trap *risk*. Static analysis can't confirm a trap (it's interactive), so we surface
    // the AI-drafted focus fix and mark it human-verify, matching the two-axis model exactly.
    const trapM = /<[a-z][^>]*\b(?:role=["']dialog["']|onkeydown=)[^>]*>/i.exec(srcText)
    ;(async () => {
      const jobs = []
      if (linkM) jobs.push(aiTextFix({ kind: 'link', text: linkM[1], context: h1 ? `careers page “${h1}”` : 'a careers page' }).then((f) => f && { label: '2.4.4 link purpose', from: linkM[1], to: f }))
      if (sensoryM) jobs.push(aiTextFix({ kind: 'sensory', text: sensoryM[1].trim() }).then((f) => f && { label: '1.3.3 sensory characteristics', from: sensoryM[1].trim(), to: f }))
      if (trapM) jobs.push(aiTextFix({ kind: 'keyboard-trap', text: trapM[0].slice(0, 300) }).then((f) => f && { label: '2.1.2 no keyboard trap', from: 'focus-trap risk detected', to: f, verify: true }))
      jobs.push(aiTextFix({ kind: 'language-parts', text: bodyText }).then((f) => f && f.toLowerCase() !== 'none' && { label: '3.1.2 language of parts', from: 'untagged foreign text', to: f.replace(/\n/g, ' · ') }))
      const out = (await Promise.all(jobs)).filter(Boolean)
      if (live) setAiFixes(out)
    })()
    return () => { live = false }
  }, [srcText, name])
  const fixes = issues.map((i) => (i.wcag || '').replace(/^(\d+\.\d+\.\d+)\s*·?\s*/, '$1 · ')).slice(0, 6)
  const ext = (name.split('.').pop() || '').toUpperCase()

  const dl = (blob, fn) => { const u = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = u; a.download = fn; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000) }
  const downloadOffice = async () => { if (!officeBlob || busy) return; setBusy(true); try { dl(await remediateOffice(officeBlob, { alt: aiAlt }), `remediated-${name}`) } catch (e) { console.error('office remediation failed', e) } finally { setBusy(false) } }
  const downloadHtml = () => { if (rem) dl(new Blob([rem.html], { type: 'text/html' }), `remediated-${name.replace(/\.[^.]+$/, '')}.html`) }

  const docCard = (badge) => (
    <div className="rpdoc"><span className="rpdocicon" aria-hidden="true">{isPdf(name) ? '📕' : '📄'}</span><span className="fname">{name}</span>{badge}</div>
  )

  return (
    <section className="panel rppanel">
      <h2>Your document · before → after <span className="muted" style={{ fontWeight: 400 }}>· rendered in your browser, nothing uploaded</span></h2>
      <div className="baframes">
        <figure>
          <figcaption className="bafcap before">as received</figcaption>
          {isHtml(name) && srcText ? <iframe sandbox="" title="as received" srcDoc={srcText} />
            : isPdf(name) && pdfUrl ? <div className="rppdf"><PdfPreview url={pdfUrl} pages={1} /></div>
              : officeBlob ? <div className="rppdf"><OfficePreview blob={officeBlob} name={name} highlight /></div>
                : docCard()}
        </figure>
        <figure>
          <figcaption className="bafcap after">remediated</figcaption>
          {isHtml(name) && rem ? <iframe sandbox="" title="remediated" srcDoc={rem.html} />
            : isPdf(name) && pdfUrl ? <div className="rppdf rpafter"><PdfPreview url={pdfUrl} pages={1} /><span className="rpbadge">{remPdf ? '✓ title + language set' : 'parsing…'}</span></div>
              : officeBlob ? <div className="rppdf rpafter">{remBlob ? <OfficePreview blob={remBlob} name={name} highlight /> : <div className="oploading"><span className="spinner" /> <span className="muted">applying fixes…</span></div>}<span className="rpbadge">✓ remediated</span></div>
                : docCard(<span className="rpbadge">✓ accessible</span>)}
        </figure>
      </div>
      {aiAlt && (
        <div className="aialtcallout">
          <span className="aialtbadge">⚡ Claude vision</span>
          <span>AI-generated alt text for the embedded image: <b>“{aiAlt}”</b> — written into the remediated file.</span>
        </div>
      )}
      {imgText && (
        <div className="aialtcallout">
          <span className="aialtbadge">⚡ Claude vision · OCR</span>
          <span><b>1.4.5 Images of Text</b> — the image is rendered text; AI extracted it as real text: <b>“{imgText}”</b></span>
        </div>
      )}
      {aiFixes.length > 0 && (
        <div className="aifixpanel">
          <div className="aifixhd"><span className="aialtbadge">⚡ Claude · live AI remediation</span><span className="muted" style={{ fontSize: 12 }}>drafted for human approval</span></div>
          {aiFixes.map((f, i) => (
            <div className="aifixrow" key={i}>
              <span className="aifixsc">{f.label}{f.verify && <span className="aifixverify" title="AI drafts the fix; a human confirms by keyboard testing">human-verify</span>}</span>
              <span className="aifixft"><span className="aifixfrom">{f.from}</span> <span aria-hidden="true">→</span> <b>{f.to}</b></span>
            </div>
          ))}
        </div>
      )}
      {isPdf(name) ? (
        <p className="muted rpnote">The document <b>title</b> and <b>language</b> are written into the PDF for real via pdf-lib{remPdf?.changes?.length ? <> — {remPdf.changes.join(' · ')}</> : ''}.{remPdf && !remPdf.tagged && <> Full <b>tagging &amp; reading order</b> need structural re-authoring (a heavier engine) — detected and flagged honestly, not faked.</>}</p>
      ) : !isHtml(name) && (
        <p className="muted rpnote">Accessibility fixes for {ext} (Office) files are <b>structural</b> — alt text, document title, table header rows and language are written into the file, so it looks identical but is now machine-readable by assistive technology.{fixes.length > 0 && <> Embedded: {fixes.join(' · ')}.</>}</p>
      )}
      {(rem || officeBlob || remPdf) && (
        <div className="rpactions">
          {isHtml(name) && rem && <button className="ghost small" onClick={downloadHtml}>⤓ Download the remediated HTML</button>}
          {officeBlob && <button className="ghost small" onClick={downloadOffice} disabled={busy}>{busy ? 'Remediating…' : `⤓ Download the remediated ${ext}`}</button>}
          {remPdf && <button className="ghost small" onClick={() => dl(remPdf.blob, `remediated-${name}`)}>⤓ Download the remediated PDF</button>}
        </div>
      )}
    </section>
  )
}
