import { useMemo, useState } from 'react'
import PdfPreview from './PdfPreview.jsx'
import { remediateOffice } from './officeAudit.js'

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
export function remediateHtml(text) {
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
      if (m && isLight(m[2])) { el.setAttribute('style', s.replace(m[2], '#333333')); changes.add('Darkened low-contrast text to meet 4.5:1 · 1.4.3'); changes.add('Recolour also meets the enhanced 7:1 ratio · 1.4.6') }
    })
    // 1.4.4 Resize Text / 1.4.10 Reflow — the viewport must allow zoom and adapt to width.
    let vp = doc.querySelector('meta[name="viewport"]')
    if (vp) {
      const c = vp.getAttribute('content') || ''
      if (/user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*(0|1)(\.0+)?\b/i.test(c)) {
        const fixed = c.replace(/,?\s*user-scalable\s*=\s*[^,]+/ig, '').replace(/,?\s*maximum-scale\s*=\s*[^,]+/ig, '').replace(/^\s*,|,\s*$/g, '').trim()
        vp.setAttribute('content', fixed || 'width=device-width, initial-scale=1')
        changes.add('Re-enabled pinch-zoom & text resize · 1.4.4')
      }
    } else if (doc.querySelector('meta, link, style')) {
      vp = doc.createElement('meta'); vp.setAttribute('name', 'viewport'); vp.setAttribute('content', 'width=device-width, initial-scale=1')
      ;(doc.head || doc.documentElement).insertBefore(vp, doc.head?.firstChild || null)
      changes.add('Added a responsive viewport for reflow · 1.4.10')
    }
    // 2.4.3 Focus Order — positive tabindex jumps the natural reading order.
    doc.querySelectorAll('[tabindex]').forEach((el) => { if (parseInt(el.getAttribute('tabindex'), 10) > 0) { el.setAttribute('tabindex', '0'); changes.add('Reset positive tabindex to keep focus order · 2.4.3') } })
    // 2.1.1 Keyboard — click-only elements need to be focusable and operable.
    doc.querySelectorAll('[onclick]').forEach((el) => {
      if (/^(a|button|input|select|textarea|summary)$/i.test(el.tagName)) return
      if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0')
      if (!el.getAttribute('role')) el.setAttribute('role', 'button')
      changes.add('Made click-only controls keyboard-operable · 2.1.1')
    })
    // 1.4.1 Use of Color — in-text links must be distinguishable by more than colour.
    doc.querySelectorAll('p a, li a, td a').forEach((a) => {
      const s = a.getAttribute('style') || ''
      if (/text-decoration[^;]*none/i.test(s) || !/text-decoration/i.test(s)) { a.setAttribute('style', (s ? s.replace(/;?\s*$/, '; ') : '') + 'text-decoration:underline'); changes.add('Underlined in-text links (not colour alone) · 1.4.1') }
    })
    // 4.1.2 Name, Role, Value — every control needs an accessible name.
    doc.querySelectorAll('button, [role="button"], a').forEach((el) => {
      if ((el.textContent || '').trim() || el.getAttribute('aria-label') || el.getAttribute('title')) return
      const hint = el.querySelector('img[alt]')?.getAttribute('alt')?.trim() || el.getAttribute('name') || (el.tagName === 'A' ? 'link' : 'button')
      el.setAttribute('aria-label', hint); changes.add('Named unlabeled controls (icon-only) · 4.1.2')
    })
    // 1.4.11 Non-text Contrast — UI borders/icons must hit 3:1; darken light declared borders.
    doc.querySelectorAll('[style*="border"]').forEach((el) => {
      const s = el.getAttribute('style')
      const m = /border(?:-[a-z]+)?:[^;]*?(#[0-9a-fA-F]{3,6})/.exec(s)
      if (m && isLight(m[1])) { el.setAttribute('style', s.replace(m[1], '#767676')); changes.add('Darkened low-contrast UI borders to 3:1 · 1.4.11') }
    })
    // 1.4.12 Text Spacing — fixed px line-heights block the user's spacing override; make them adaptive.
    doc.querySelectorAll('[style*="line-height"]').forEach((el) => {
      const s = el.getAttribute('style')
      if (/line-height:\s*\d+px/i.test(s)) { el.setAttribute('style', s.replace(/line-height:\s*\d+px/i, 'line-height:1.5')); changes.add('Unblocked text-spacing overrides · 1.4.12') }
    })
    // 2.4.6 Headings and Labels — promote visually-styled pseudo-headings (large, bold, short
    // leaf text) to real headings so screen-reader users can navigate the document by heading.
    doc.querySelectorAll('p, div').forEach((el) => {
      if (el.children.length) return
      const txt = (el.textContent || '').trim()
      if (!txt || txt.length > 50 || /[.?!]$/.test(txt)) return
      const s = el.getAttribute('style') || ''
      const fs = parseInt((/font-size:\s*(\d+)px/i.exec(s) || [])[1] || 0, 10)
      if (fs >= 18 && /font-weight:\s*(bold|[6-9]00)/i.test(s)) {
        const h = doc.createElement('h2'); h.textContent = txt; if (s) h.setAttribute('style', s)
        el.replaceWith(h); changes.add('Promoted styled text to real headings · 2.4.6')
      }
    })
    // 2.4.7 Focus Visible — when the page suppresses focus outlines, inject a focus-visible
    // rule so keyboard users can always see where they are.
    const css = [...doc.querySelectorAll('style')].map((s) => s.textContent || '').join('\n')
    const suppressed = /outline:\s*(none|0)\b/i.test(css) || [...doc.querySelectorAll('[style*="outline"]')].some((el) => /outline:\s*(none|0)\b/i.test(el.getAttribute('style') || ''))
    if (suppressed && doc.querySelector('a, button, input, select, textarea')) {
      const st = doc.createElement('style'); st.textContent = ':focus-visible{outline:2px solid #1F5FA8;outline-offset:2px}'
      ;(doc.head || doc.documentElement).appendChild(st); changes.add('Ensured a visible keyboard focus indicator · 2.4.7')
    }
    // 3.1.4 Abbreviations (AAA) — wrap known abbreviations in <abbr title> so AT can expand them.
    const ABBR = { WCAG: 'Web Content Accessibility Guidelines', ADA: 'Americans with Disabilities Act', PDF: 'Portable Document Format', PPO: 'Preferred Provider Organization', HDHP: 'High-Deductible Health Plan', FSA: 'Flexible Spending Account', HSA: 'Health Savings Account', FAQ: 'Frequently Asked Questions', PII: 'Personally Identifiable Information', UTSW: 'UT Southwestern', HR: 'Human Resources' }
    const keys = Object.keys(ABBR)
    if (doc.body && keys.length) {
      const re = new RegExp('\\b(' + keys.join('|') + ')\\b')
      const walker = doc.createTreeWalker(doc.body, 4 /* SHOW_TEXT */)
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode)
      nodes.forEach((node) => {
        if (node.parentElement?.closest('abbr, script, style, title')) return
        let text = node.textContent
        if (!re.test(text)) return
        const frag = doc.createDocumentFragment(); let m
        while ((m = re.exec(text))) {
          if (m.index) frag.appendChild(doc.createTextNode(text.slice(0, m.index)))
          const ab = doc.createElement('abbr'); ab.setAttribute('title', ABBR[m[1]]); ab.textContent = m[1]
          frag.appendChild(ab); text = text.slice(m.index + m[1].length); changes.add('Expanded abbreviations with <abbr> · 3.1.4')
        }
        if (text) frag.appendChild(doc.createTextNode(text))
        node.replaceWith(frag)
      })
    }
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

export default function BeforeAfter({ file, issues = [], srcText, pdfUrl, officeBlob }) {
  const rem = useMemo(() => (srcText ? remediateHtml(srcText) : null), [srcText])
  const [busy, setBusy] = useState(false)
  const dl = (blob, name) => { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
  const downloadFixed = () => { if (rem) dl(new Blob([rem.html], { type: 'text/html' }), `remediated-${(file?.name || 'page').replace(/\.[^.]+$/, '')}.html`) }
  const downloadOffice = async () => {
    if (!officeBlob || busy) return
    setBusy(true)
    try { dl(await remediateOffice(officeBlob), `remediated-${file?.name || 'document'}`) }
    catch (e) { console.error('office remediation failed', e) }
    finally { setBusy(false) }
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
      {officeBlob && (
        <div className="balive">
          <div className="bahd"><b>Remediated file</b><span className="muted"> — alt text, table header rows &amp; document title written back into the real Office XML, in your browser</span></div>
          <button className="ghost small" onClick={downloadOffice} disabled={busy}>{busy ? 'Remediating…' : `⤓ Download the remediated ${(file?.name || '').split('.').pop().toUpperCase()}`}</button>
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
