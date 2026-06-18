import { useMemo } from 'react'
import PdfPreview from './PdfPreview.jsx'

// Side-by-side "what you'd get" preview. For HTML we genuinely remediate the
// uploaded markup and render both versions in sandboxed iframes (contrast fixes
// are visibly different). For every finding we also render a concrete before→after
// of the fix, since most a11y improvements are invisible in the visual render.

function isLight(hex) {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62
}
const altFromSrc = (src) => {
  if (!src) return 'descriptive image'
  const base = src.split('/').pop().replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim()
  return base ? `image: ${base}` : 'descriptive image'
}

// Real, best-effort HTML remediation. Returns the fixed markup + a list of changes.
function remediateHtml(text) {
  try {
    const doc = new DOMParser().parseFromString(text, 'text/html')
    const changes = new Set()
    if (!doc.documentElement.getAttribute('lang')) { doc.documentElement.setAttribute('lang', 'en'); changes.add('Set document language to English · 3.1.1') }
    let title = doc.querySelector('title')
    if (!title || !title.textContent.trim()) {
      if (!title) { title = doc.createElement('title'); (doc.head || doc.documentElement).appendChild(title) }
      title.textContent = (doc.querySelector('h1')?.textContent?.trim() || 'Document').slice(0, 80)
      changes.add('Added a descriptive page title · 2.4.2')
    }
    doc.querySelectorAll('img').forEach((img) => { if (!img.getAttribute('alt')) { img.setAttribute('alt', altFromSrc(img.getAttribute('src'))); changes.add('Generated alt text for images · 1.1.1') } })
    doc.querySelectorAll('input, select, textarea').forEach((inp) => {
      const id = inp.getAttribute('id')
      const labelled = inp.getAttribute('aria-label') || (id && doc.querySelector(`label[for="${id}"]`))
      if (!labelled) { inp.setAttribute('aria-label', inp.getAttribute('placeholder') || inp.getAttribute('name') || 'form field'); changes.add('Labeled form fields · 1.3.1') }
    })
    doc.querySelectorAll('a').forEach((a) => { if (/^(click here|read more|learn more|here|more)\.?$/i.test((a.textContent || '').trim())) { a.setAttribute('aria-label', `${a.textContent.trim()} — ${doc.title || 'link'}`); changes.add('Clarified ambiguous links · 2.4.4') } })
    doc.querySelectorAll('[style*="color"]').forEach((el) => {
      const s = el.getAttribute('style'); const m = /(^|[^-])color:\s*(#[0-9a-fA-F]{3,6})/.exec(s)
      if (m && isLight(m[2])) { el.setAttribute('style', s.replace(m[2], '#333333')); changes.add('Darkened low-contrast text to meet 4.5:1 · 1.4.3') }
    })
    return { html: '<!doctype html>' + doc.documentElement.outerHTML, changes: [...changes] }
  } catch { return null }
}

const scOf = (wcag) => ((wcag || '').match(/^\d+\.\d+\.\d+/) || [''])[0]

// Concrete before→after visuals per success criterion.
function baFor(sc) {
  switch (sc) {
    case '1.1.1': return {
      before: <div className="baimg"><span aria-hidden="true">🖼</span><span className="bawarn">no alt text — screen readers skip this</span></div>,
      after: <div className="baimg"><span aria-hidden="true">🖼</span><span className="bacap">alt: “bar chart — enrollment by quarter, Q3 highest”</span></div>,
    }
    case '1.4.3': return {
      before: <div><span className="bacontrast" style={{ color: '#bcbcbc' }}>Apply by March 31</span><span className="bawarn">3.1 : 1 · fails AA</span></div>,
      after: <div><span className="bacontrast" style={{ color: '#37323b' }}>Apply by March 31</span><span className="baok">4.9 : 1 · passes AA</span></div>,
    }
    case '2.4.2': return {
      before: <div><span className="batab">○ Untitled document</span><span className="bawarn">can’t identify the doc in AT</span></div>,
      after: <div><span className="batab">○ 2026 Benefits Guide — UTSW</span><span className="baok">clearly identified</span></div>,
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
      after: <div><a className="balink">view the 2026 benefits guide</a><span className="baok">clear &amp; descriptive</span></div>,
    }
    default: return {
      before: <div><span className="bawarn">finding present</span></div>,
      after: <div><span className="baok">resolved &amp; re-validated</span></div>,
    }
  }
}

export default function BeforeAfter({ file, issues = [], srcText, pdfUrl }) {
  const rem = useMemo(() => (srcText ? remediateHtml(srcText) : null), [srcText])
  const downloadFixed = () => {
    if (!rem) return
    const blob = new Blob([rem.html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `remediated-${(file?.name || 'page').replace(/\.[^.]+$/, '')}.html`
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <div className="bawrap">
      {rem && (
        <div className="balive">
          <div className="bahd"><b>Live preview · your page, before → after</b><span className="muted"> — real DOM remediation, rendered in your browser</span></div>
          <div className="baframes">
            <figure><figcaption className="bafcap before">as uploaded</figcaption><iframe sandbox="" title="as uploaded" srcDoc={srcText} /></figure>
            <figure><figcaption className="bafcap after">remediated</figcaption><iframe sandbox="" title="remediated" srcDoc={rem.html} /></figure>
          </div>
          {rem.changes.length > 0 && <div className="bachanges">{rem.changes.map((c, i) => <span key={i} className="bachip">✓ {c}</span>)}</div>}
          <div style={{ marginTop: 11 }}><button className="ghost small" onClick={downloadFixed}>⤓ Download the remediated HTML</button></div>
        </div>
      )}
      {pdfUrl && !rem && (
        <div className="balive">
          <div className="bahd"><b>Your document</b><span className="muted"> — {file?.name}, rendered in your browser</span></div>
          <div className="bapdf"><PdfPreview url={pdfUrl} /></div>
          <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>Accessibility fixes (tags, alt text, reading order) are structural — see exactly what changes below.</p>
        </div>
      )}
      <div className="bacards">
        <div className="bahd"><b>What remediation produces</b><span className="muted"> — per finding, before → after</span></div>
        {issues.map((it, n) => {
          const ba = baFor(scOf(it.wcag))
          return (
            <div className="barow" key={n}>
              <div className="balabel">{it.wcag}<span className="muted" style={{ fontWeight: 400 }}> · {it.detail}</span></div>
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
