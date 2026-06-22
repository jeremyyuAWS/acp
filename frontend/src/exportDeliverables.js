// Generate updated copies of the two customer deliverables — the WCAG coverage
// matrix (Excel) and the AccessOps method deck (PowerPoint) — with an added
// "Status" column that reflects what is actually live in the platform today.
//
// We edit the original OOXML *additively* (inject one column, preserve every
// existing cell, style, and the slide design) rather than regenerate, so the
// downloads look exactly like the originals plus the new column. JSZip is
// already a dependency.

const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// --- Status vocabulary: what the platform genuinely does for each criterion ---
// Concise so it fits the new column. Live = shipped & working; Detected = found
// but auto-fix is on the roadmap; Roadmap/Partner baseline = not platform-built yet.
const STATUS = {
  '1.1.1': 'Live · AI vision', '1.2.1': 'Live · Whisper', '1.2.2': 'Live · Whisper', '1.2.3': 'Live · transcript',
  '1.3.1': 'Live · auto', '1.3.2': 'Covered · HITL', '1.3.3': 'Live · AI',
  // Phase 2 — covered via detect-and-route to a human reviewer
  '1.2.4': 'Covered · HITL', '1.2.5': 'Covered · HITL', '1.4.13': 'Covered · HITL', '2.1.4': 'Covered · HITL',
  '2.2.1': 'Covered · HITL', '2.2.2': 'Covered · HITL', '2.5.1': 'Covered · HITL', '2.5.2': 'Covered · HITL',
  '2.5.4': 'Covered · HITL', '3.2.1': 'Covered · HITL', '3.2.2': 'Covered · HITL', '3.3.1': 'Covered · HITL',
  '3.3.3': 'Covered · HITL', '3.3.4': 'Covered · HITL', '4.1.3': 'Covered · HITL',
  // Phase 3 — AAA our engines already satisfy (Live) + the runtime AAA routed to HITL
  '1.4.6': 'Live · auto', '1.4.9': 'Live · AI OCR', '2.4.9': 'Live · AI', '3.1.4': 'Live · auto',
  '1.3.6': 'Covered · HITL', '1.4.8': 'Covered · HITL', '2.1.3': 'Covered · HITL', '2.2.3': 'Covered · HITL',
  '2.2.4': 'Covered · HITL', '2.2.5': 'Covered · HITL', '2.2.6': 'Covered · HITL', '2.3.2': 'Covered · HITL',
  '2.3.3': 'Covered · HITL', '2.4.8': 'Covered · HITL', '2.4.10': 'Covered · HITL', '2.4.11': 'Covered · HITL',
  '2.4.12': 'Covered · HITL', '2.4.13': 'Covered · HITL', '2.5.5': 'Covered · HITL', '2.5.6': 'Covered · HITL',
  '2.5.7': 'Covered · HITL', '3.1.3': 'Covered · HITL', '3.1.5': 'Covered · HITL', '3.1.6': 'Covered · HITL',
  '3.2.5': 'Covered · HITL', '3.3.5': 'Covered · HITL', '3.3.6': 'Covered · HITL', '3.3.7': 'Covered · HITL',
  '3.3.8': 'Covered · HITL', '3.3.9': 'Covered · HITL',
  '1.4.1': 'Live · auto', '1.4.3': 'Live · auto', '1.4.4': 'Live · auto', '1.4.5': 'Live · AI OCR',
  '1.4.10': 'Live · auto', '1.4.11': 'Live · auto', '1.4.12': 'Live · auto',
  '2.1.1': 'Live · auto', '2.1.2': 'Live · AI + human', '2.4.1': 'Roadmap', '2.4.2': 'Live · auto', '2.4.4': 'Live · AI',
  '2.4.3': 'Live · auto', '2.4.6': 'Live · auto', '2.4.7': 'Live · auto', '4.1.2': 'Live · auto',
  '3.1.1': 'Live · auto', '3.1.2': 'Live · AI', '3.3.2': 'Live · auto', 'PDF/UA': 'Roadmap',
}
export function statusFor(sc, source = '', phase = '') {
  const key = (sc || '').trim()
  if (STATUS[key]) return STATUS[key]
  if (/Shipped/i.test(source)) return 'Live · demo'
  if (/Partner baseline/i.test(source)) return 'Partner baseline'
  if (/Phase 1/i.test(phase)) return 'Roadmap · P1'
  if (/Phase 2/i.test(phase)) return 'Roadmap · P2'
  if (/Phase 3|AAA|Optional/i.test(phase)) return 'Roadmap · P3'
  return 'Planned'
}

// ---------- Excel: add a "Status" column to the "Coverage Matrix" sheet ----------
export function transformSheetXml(xml) {
  // widen the used range by one column (O -> P)
  let out = xml.replace(/<dimension ref="A1:O(\d+)"\/>/, '<dimension ref="A1:P$1"/>')
  // give the new column a width
  out = out.replace('</cols>', '<col width="34" customWidth="1" min="16" max="16"/></cols>')
  // append a P-cell to every row (header gets the label, data rows get the status)
  out = out.replace(/<row r="(\d+)"([^>]*)>([\s\S]*?)<\/row>/g, (m, n, attrs, inner) => {
    if (n === '1') return `<row r="1"${attrs}>${inner}<c r="P1" s="17" t="inlineStr"><is><t>Status</t></is></c></row>`
    const sc = (inner.match(/<c r="A\d+"[^>]*>(?:<is><t>([^<]*)<\/t>)?/) || [])[1] || ''
    const src = (inner.match(/<c r="H\d+"[^>]*><is><t>([^<]*)<\/t>/) || [])[1] || ''
    const phase = (inner.match(/<c r="J\d+"[^>]*><is><t>([^<]*)<\/t>/) || [])[1] || ''
    const st = esc(statusFor(sc, src, phase))
    return `<row r="${n}"${attrs}>${inner}<c r="P${n}" s="19" t="inlineStr"><is><t>${st}</t></is></c></row>`
  })
  return out
}

export async function transformXlsx(zip) {
  const path = 'xl/worksheets/sheet2.xml' // "Coverage Matrix"
  const xml = await zip.file(path).async('string')
  zip.file(path, transformSheetXml(xml))
  return zip
}

// ---------- PowerPoint: add a "Status" column to the table on each slide ----------
const COLID_EXT = (val) => `<a:extLst><a:ext uri="{9D8B030D-6E8A-4147-A177-3AD203B41FA5}"><a16:colId xmlns:a16="http://schemas.microsoft.com/office/drawing/2014/main" val="${val}"/></a:ext></a:extLst>`

// set the single visible run's text (and, for status cells, its colour) on a cloned <a:tc>
function fillCell(tplTc, text, recolor) {
  let tc = tplTc
  if (recolor) {
    tc = tc.replace(/ i="1"/, '') // drop italic for the status text
    const color = /^Live/.test(text) ? '3B6D11' : /^Detected/.test(text) ? '1F5FA8' : '854F0B'
    tc = tc.replace(/<a:srgbClr val="[0-9A-Fa-f]{6}"\/>/, `<a:srgbClr val="${color}"/>`) // first srgbClr = run text colour
  }
  let first = true
  tc = tc.replace(/<a:t>[\s\S]*?<\/a:t>/g, () => (first ? ((first = false), `<a:t>${esc(text)}</a:t>`) : '<a:t></a:t>'))
  return tc
}

export function transformSlideXml(xml) {
  const tbl = xml.match(/<a:tbl>[\s\S]*?<\/a:tbl>/)
  if (!tbl) return xml
  let table = tbl[0]

  // 1) tblGrid — shrink the existing columns proportionally and add a status column,
  //    keeping the total table width constant so nothing overflows the slide.
  const grid = table.match(/<a:tblGrid>[\s\S]*?<\/a:tblGrid>/)[0]
  const widths = [...grid.matchAll(/<a:gridCol w="(\d+)">/g)].map((mm) => +mm[1])
  const total = widths.reduce((a, b) => a + b, 0)
  const statusW = Math.round(total * 0.2)
  const f = (total - statusW) / total
  let newGrid = grid.replace(/<a:gridCol w="(\d+)">/g, (mm, w) => `<a:gridCol w="${Math.round(+w * f)}">`)
  newGrid = newGrid.replace('</a:tblGrid>', `<a:gridCol w="${statusW}">${COLID_EXT(20005)}</a:gridCol></a:tblGrid>`)
  table = table.replace(grid, newGrid)

  // 2) capture templates: header cell, a data cell, and a merged (section) cell
  const rows = table.match(/<a:tr[ >][\s\S]*?<\/a:tr>/g) || []
  const tcsOf = (r) => r.match(/<a:tc[ >][\s\S]*?<\/a:tc>/g) || []
  const headerTpl = tcsOf(rows[0]).slice(-1)[0]
  // a real DATA row — skip the header (row 0) and any section/gridSpan rows, so status
  // cells inherit body styling (not the bold header band).
  const dataRow = rows.slice(1).find((r) => !r.includes('gridSpan=') && tcsOf(r).length > 1) || rows[1] || rows[0]
  const dataTpl = tcsOf(dataRow).slice(-1)[0]
  const mergeRow = rows.find((r) => r.includes('gridSpan='))
  const mergeTpl = mergeRow ? tcsOf(mergeRow).slice(-1)[0] : null

  // 3) append a status cell to each row
  rows.forEach((row, i) => {
    let newRow
    if (i === 0) {
      newRow = row.replace('</a:tr>', `${fillCell(headerTpl, 'Status', false)}</a:tr>`)
    } else if (row.includes('gridSpan=') && mergeTpl) {
      // section header row spans the table — widen the span and add one more merged cell
      newRow = row.replace(/gridSpan="(\d+)"/, (mm, s) => `gridSpan="${+s + 1}"`).replace('</a:tr>', `${mergeTpl}</a:tr>`)
    } else {
      // the Code cell may carry a footnote marker (e.g. "1.4.4 *") — normalise to the bare SC
      const raw = ((row.match(/<a:t>([^<]*)<\/a:t>/) || [])[1] || '').trim()
      const sc = raw.match(/\d+\.\d+\.\d+/)?.[0] || raw
      newRow = row.replace('</a:tr>', `${fillCell(dataTpl, statusFor(sc), true)}</a:tr>`)
    }
    table = table.replace(row, newRow)
  })

  return xml.replace(tbl[0], table)
}

export async function transformPptx(zip) {
  const slides = Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))
  for (const path of slides) {
    const xml = await zip.file(path).async('string')
    zip.file(path, transformSlideXml(xml))
  }
  return zip
}

// ---------- browser entry points: fetch the embedded source, transform, download ----------
async function loadZip(url) {
  const JSZip = (await import('jszip')).default
  const buf = await (await fetch(url)).arrayBuffer()
  return JSZip.loadAsync(buf)
}
function download(blob, filename) {
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(u), 1000)
}

export async function downloadUpdatedXlsx() {
  const zip = await transformXlsx(await loadZip('/exports/coverage-matrix.xlsx'))
  const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  download(blob, 'WCAG_Coverage_LOE_Analysis_with_Status.xlsx')
}

export async function downloadUpdatedPptx() {
  const zip = await transformPptx(await loadZip('/exports/method-deck.pptx'))
  const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })
  download(blob, 'MovaiO_AccessOps_Method_Slides_with_Status.pptx')
}
