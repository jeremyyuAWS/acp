// HTML companion to the certification PDF (pdfReport.js). Renders the SAME report
// model (reportModel.js) as a single self-contained, WCAG-conformant HTML document —
// so the two exports can never drift.
//
// Why HTML as well as PDF: HTML is itself screen-reader-friendly (fitting for an
// accessibility product), linkable, and trivially embeddable/shareable. This output
// dogfoods the product on its own report: it passes every Level A/AA rule in
// frontend/src/rules (see htmlReport.test.js) — semantic headings, table headers +
// captions, a skip link + main landmark, a declared language, a zoom-friendly
// viewport, visible focus, and 4.5:1-safe ink on white.
//
// Self-contained: all CSS is inlined in a <style> block and the logo is embedded as a
// data URI — the downloaded file makes ZERO external requests.

import { buildFileCertificationModel, INK, MUTED, GREEN, AMBER, RED, PLUM, BLUE, CW } from './reportModel.js'

const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const slug = (s) => 'sec-' + String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')

// Map a model ink (hex) to a CSS class so palette colours live in the <style> block,
// not inline — keeping the 1.4.3 / 1.4.11 inline-style scanners quiet regardless.
const COLOR_CLASS = { [INK]: 'c-ink', [MUTED]: 'c-muted', [GREEN]: 'c-good', [AMBER]: 'c-warn', [RED]: 'c-bad', [PLUM]: 'c-plum', [BLUE]: 'c-info' }
const colorClass = (hex) => COLOR_CLASS[hex] || 'c-ink'

// A text block's options → a class list. Size < 9 → small print; explicit bold → lead.
const textClasses = (o = {}) => {
  const cls = [colorClass(o.color)]
  if (o.bold) cls.push('lead')
  if ((o.size || 10) <= 8.5) cls.push('fine')
  else if ((o.size || 10) < 9.5) cls.push('small')
  return cls.join(' ')
}

// ── Ring (score dial) as inline SVG — mirrors the PDF cover ring ──
function ringSvg(score, hex) {
  const s = Math.max(0, Math.min(100, Math.round(score || 0)))
  const R = 34, C = 2 * Math.PI * R, on = (s / 100) * C
  const cls = colorClass(hex)
  return `<svg class="ring ${cls}" viewBox="0 0 84 84" role="img" aria-label="Accessibility score ${s} out of 100">
  <circle cx="42" cy="42" r="${R}" fill="none" stroke="#E9E5EE" stroke-width="8"></circle>
  <circle cx="42" cy="42" r="${R}" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"
    stroke-dasharray="${on.toFixed(2)} ${(C - on).toFixed(2)}" transform="rotate(-90 42 42)"></circle>
  <text x="42" y="42" text-anchor="middle" dominant-baseline="central" class="ring-num">${s}</text>
  <text x="42" y="57" text-anchor="middle" dominant-baseline="central" class="ring-den">/ 100</text>
</svg>`
}

// ── Donut as inline SVG + a text legend (never colour-only: 1.4.1) ──
function donutSvg(items) {
  const data = (items || []).filter((it) => (it.value || 0) > 0)
  const total = data.reduce((s, it) => s + it.value, 0)
  const R = 34, Cc = 2 * Math.PI * R
  let offset = 0
  const rings = total > 0 ? data.map((it) => {
    const frac = it.value / total
    const seg = `<circle cx="42" cy="42" r="${R}" fill="none" stroke="${esc(it.color)}" stroke-width="16"
      stroke-dasharray="${(frac * Cc).toFixed(2)} ${((1 - frac) * Cc).toFixed(2)}"
      stroke-dashoffset="${(-offset * Cc).toFixed(2)}" transform="rotate(-90 42 42)"></circle>`
    offset += frac
    return seg
  }).join('\n') : `<circle cx="42" cy="42" r="${R}" fill="none" stroke="#EEECF0" stroke-width="16"></circle>`
  const label = total > 0
    ? `<text x="42" y="40" text-anchor="middle" dominant-baseline="central" class="donut-num">${total}</text><text x="42" y="52" text-anchor="middle" dominant-baseline="central" class="ring-den">criteria</text>`
    : `<text x="42" y="42" text-anchor="middle" dominant-baseline="central" class="ring-den">No data</text>`
  const svg = `<svg class="donut" viewBox="0 0 84 84" role="img" aria-label="Coverage: ${esc((items || []).map((it) => `${it.value} ${it.label}`).join(', '))}">
${rings}
${label}
</svg>`
  const legend = `<ul class="legend">` + (items || []).map((it) =>
    `<li><span class="swatch" style="background:${esc(it.color)}" aria-hidden="true"></span><span class="legend-label">${esc(it.label)}</span><span class="legend-val">${esc(it.value)}</span></li>`
  ).join('') + `</ul>`
  return `<div class="donut-wrap">${svg}${legend}</div>`
}

// ── Horizontal bar chart — value shown as text, not colour-only ──
function barChart(items) {
  const mx = Math.max(1, ...(items || []).map((i) => i.value))
  const rows = (items || []).map((it) => {
    const pct = Math.max(2, Math.round((it.value / mx) * 100))
    return `<li class="bar-row">
      <span class="bar-label">${esc(it.label)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${pct}%;background:${esc(it.color || PLUM)}"></span></span>
      <span class="bar-val">${esc(it.value)}</span>
    </li>`
  }).join('')
  return `<ul class="bars">${rows}</ul>`
}

function metricGrid(cards) {
  const cells = (cards || []).map((c) =>
    `<div class="metric"><dt>${esc(c.label)}</dt><dd class="${colorClass(c.color)}">${esc(c.value)}</dd></div>`
  ).join('')
  return `<dl class="metrics">${cells}</dl>`
}

// Table with caption, column-group widths, a row header on the first column, and
// scoped column headers — everything ACP's 1.3.1 check wants to see.
function table(b) {
  const widths = b.widths || b.headers.map(() => CW / b.headers.length)
  const tot = widths.reduce((s, w) => s + w, 0)
  const cols = widths.map((w) => `<col style="width:${((w / tot) * 100).toFixed(1)}%">`).join('')
  const thead = `<thead><tr>` + b.headers.map((h) => `<th scope="col">${esc(h)}</th>`).join('') + `</tr></thead>`
  const tbody = `<tbody>` + b.rows.map((r) => `<tr>` + r.map((cell, i) =>
    i === 0 ? `<th scope="row">${esc(cell)}</th>` : `<td>${esc(cell)}</td>`
  ).join('') + `</tr>`).join('') + `</tbody>`
  const cap = b.caption ? `<caption class="sr-only">${esc(b.caption)}</caption>` : ''
  return `<div class="table-wrap"><table><colgroup>${cols}</colgroup>${cap}${thead}${tbody}</table></div>`
}

// Render the ordered block list into <section> groups keyed by heading.
function renderBlocks(blocks) {
  let out = ''
  let open = false
  const closeSection = () => { if (open) { out += '\n</section>'; open = false } }
  for (const b of blocks) {
    switch (b.k) {
      case 'heading': {
        closeSection()
        const id = slug(b.text)
        out += `\n<section aria-labelledby="${id}">\n<h2 id="${id}">${esc(b.text)}</h2>`
        open = true
        break
      }
      case 'pageBreak':
        closeSection()
        out += `\n<div class="page-break" aria-hidden="true"></div>`
        break
      case 'text':
        out += `\n<p class="${textClasses(b.o)}">${esc(b.text)}</p>`
        break
      case 'callout': {
        const tone = b.o?.color === GREEN ? 'good' : b.o?.color === AMBER ? 'warn' : 'plum'
        out += `\n<p class="callout ${tone}">${esc(b.text)}</p>`
        break
      }
      case 'bullets':
        out += `\n<ul class="bullets">` + (b.items || []).map((it) => `<li>${esc(it)}</li>`).join('') + `</ul>`
        break
      case 'metricGrid':
        out += `\n${metricGrid(b.cards)}`
        break
      case 'donut':
        out += `\n${donutSvg(b.items)}`
        break
      case 'barChart':
        out += `\n${barChart(b.items)}`
        break
      case 'table':
        out += `\n${table(b)}`
        break
      case 'beforeAfter':
        out += '\n' + (b.items || []).map((it) => (
          `<div class="ba-item">` +
          `<p class="ba-label">${esc(it.label)}</p>` +
          (it.note ? `<p class="ba-note">${esc(it.note)}</p>` : '') +
          `<div class="ba-band ba-before"><span class="ba-tag">Before</span><code>${esc(String(it.before == null ? '' : it.before))}</code></div>` +
          `<div class="ba-band ba-after"><span class="ba-tag">After</span><code>${esc(String(it.after == null ? '' : it.after))}</code></div>` +
          `</div>`
        )).join('')
        break
      default:
        break
    }
  }
  closeSection()
  return out
}

const STYLE = `
  :root { --ink:${INK}; --muted:${MUTED}; --line:${'#E4E0E8'}; --plum:${PLUM}; --paper:#fff; --wash:#F7F5F9; }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: #EDEAF0; color: var(--ink);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .skip-link { position: absolute; left: 8px; top: -48px; background: var(--plum); color: #fff;
    padding: 10px 16px; border-radius: 6px; z-index: 10; transition: top .15s; }
  .skip-link:focus { top: 8px; }
  a:focus-visible, .skip-link:focus-visible, [tabindex]:focus-visible { outline: 3px solid var(--plum); outline-offset: 2px; }
  .page { max-width: 900px; margin: 24px auto; background: var(--paper); padding: 40px 48px;
    box-shadow: 0 1px 4px rgba(43,35,48,.12); border-radius: 8px; }
  .cover { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;
    border-bottom: 2px solid var(--plum); padding-bottom: 20px; margin-bottom: 8px; }
  .cover-main { min-width: 0; }
  .logo { height: 34px; width: auto; margin-bottom: 14px; }
  h1 { font-size: 27px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -.01em; }
  .subtitle { font-size: 16px; color: var(--muted); margin: 0 0 10px; word-break: break-word; }
  .cover-meta { list-style: none; padding: 0; margin: 0; color: var(--muted); font-size: 13px; }
  .cover-meta li { margin: 2px 0; }
  h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .04em; color: var(--plum);
    margin: 30px 0 4px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
  section > :first-child { margin-top: 0; }
  p { margin: 9px 0; }
  .lead { font-weight: 700; }
  .small { font-size: 13px; }
  .fine { font-size: 12px; }
  .c-ink { color: var(--ink); } .c-muted { color: var(--muted); }
  .c-good { color: ${GREEN}; } .c-warn { color: ${AMBER}; } .c-bad { color: ${RED}; }
  .c-plum { color: ${PLUM}; } .c-info { color: ${BLUE}; }
  .callout { border: 1px solid var(--plum); background: var(--wash); border-left-width: 5px;
    border-radius: 6px; padding: 14px 16px; margin: 12px 0; }
  .callout.good { border-color: ${GREEN}; background: #EEF5E8; }
  .callout.warn { border-color: ${AMBER}; background: #FBF1DF; }
  .bullets { margin: 8px 0; padding-left: 22px; }
  .bullets li { margin: 4px 0; }
  .ring { width: 84px; height: 84px; flex: 0 0 auto; }
  .ring-num { font-size: 22px; font-weight: 700; fill: currentColor; }
  .ring-den, .donut .ring-den { font-size: 8px; fill: var(--muted); }
  .donut-num { font-size: 16px; font-weight: 700; fill: var(--ink); }
  .donut-wrap { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; margin: 12px 0; }
  .donut { width: 120px; height: 120px; flex: 0 0 auto; }
  .legend { list-style: none; margin: 0; padding: 0; }
  .legend li { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex: 0 0 auto; }
  .legend-val { font-weight: 700; margin-left: 4px; }
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0; }
  .metric { border: 1px solid var(--line); background: #FBFAFC; border-radius: 6px; padding: 10px 12px; }
  .metric dt { font-size: 11px; text-transform: uppercase; letter-spacing: .03em; color: var(--muted); }
  .metric dd { margin: 4px 0 0; font-size: 22px; font-weight: 700; }
  .bars { list-style: none; margin: 12px 0; padding: 0; }
  .bar-row { display: grid; grid-template-columns: 150px 1fr 40px; align-items: center; gap: 10px; margin: 6px 0; }
  .bar-track { background: #EEECF0; border-radius: 3px; height: 14px; overflow: hidden; }
  .bar-fill { display: block; height: 100%; border-radius: 3px; }
  .bar-val { font-weight: 700; text-align: right; }
  .table-wrap { overflow-x: auto; margin: 12px 0; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  caption { text-align: left; }
  thead th { background: var(--plum); color: #fff; text-align: left; padding: 8px 10px; font-size: 12px; }
  tbody th, tbody td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line);
    vertical-align: top; font-weight: 400; }
  tbody th { color: var(--ink); }
  tbody tr:nth-child(even) { background: var(--wash); }
  .doc-footer { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--line);
    color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
  @media (max-width: 640px) {
    .page { padding: 24px 18px; margin: 0; border-radius: 0; }
    .metrics { grid-template-columns: repeat(2, 1fr); }
    .bar-row { grid-template-columns: 110px 1fr 34px; }
    .cover { flex-direction: column; }
  }
  @media print {
    body { background: #fff; } .page { box-shadow: none; margin: 0; max-width: none; }
    .page-break { break-before: page; }
  }
  .ba-item { margin: 0 0 16px; break-inside: avoid; }
  .ba-label { font-weight: 700; color: #4B3460; margin: 0 0 3px; }
  .ba-note { color: #55505A; font-size: 13px; margin: 0 0 6px; }
  .ba-band { display: flex; gap: 10px; align-items: flex-start; border: 1px solid #E4E0E8;
    border-left-width: 3px; border-radius: 4px; padding: 7px 9px; margin: 4px 0; }
  .ba-band code { font-family: ui-monospace, "Courier New", monospace; font-size: 12.5px;
    white-space: pre-wrap; word-break: break-word; color: #2B2330; }
  .ba-tag { font-size: 11px; font-weight: 700; letter-spacing: .04em; flex: 0 0 52px; padding-top: 1px; }
  .ba-before { background: #FBF2F1; border-left-color: #A32D2D; }
  .ba-before .ba-tag { color: #8A2A24; }
  .ba-after { background: #F0F5EA; border-left-color: #3B6D11; }
  .ba-after .ba-tag { color: #345F0F; }
`

// Build the complete standalone HTML document string from a report model.
// `logo` (optional) is a data: URI for the mova.io mark; omitted in tests.
export function certificationHtmlFromModel(model, { logo } = {}) {
  const c = model.cover || {}
  const coverMeta = (c.meta || []).map((m) => `<li>${esc(m)}</li>`).join('')
  const logoImg = logo ? `<img class="logo" src="${logo}" alt="mova.io Accessibility Platform">` : ''
  const ring = c.ring ? ringSvg(c.ring.score, c.ring.color) : ''
  const brand = 'mova.io · Accessibility Platform' + (model.footerVersion ? ` · v${esc(model.footerVersion)}` : '')
  const footer = `<footer class="doc-footer">
    <span>${brand}</span>
    <span>Confidential</span>
    ${model.footerGenerated ? `<span>Generated ${esc(model.footerGenerated)}</span>` : ''}
  </footer>`

  return `<!doctype html>
<html lang="${esc(model.lang || 'en-US')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(model.docTitle)}</title>
<style>${STYLE}</style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<div class="page">
<header class="cover">
  <div class="cover-main">
    ${logoImg}
    <h1>${esc(c.title || 'Accessibility Certification')}</h1>
    ${c.subtitle ? `<p class="subtitle">${esc(c.subtitle)}</p>` : ''}
    <ul class="cover-meta">${coverMeta}</ul>
  </div>
  ${ring}
</header>
<main id="main-content">${renderBlocks(model.blocks)}
</main>
${footer}
</div>
</body>
</html>`
}

// Pure entry point (no I/O) — used by the dogfood test.
export function certificationHtml(d, opts = {}) {
  return certificationHtmlFromModel(buildFileCertificationModel(d), opts)
}

async function logoDataUrl() {
  try {
    const url = (import.meta.env.BASE_URL || '/') + 'mova-logo.png'
    const blob = await (await fetch(url)).blob()
    return await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(null); r.readAsDataURL(blob) })
  } catch { return null }
}

// Build + download the self-contained HTML report. Mirrors exportFileCertification.
export async function exportFileCertificationHtml(d) {
  const model = buildFileCertificationModel(d)
  const logo = await logoDataUrl()
  const html = certificationHtmlFromModel(model, { logo })
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${model.filename}.html`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
