// Lightweight in-browser preview of Office (OOXML) files. We already open the zip with
// JSZip for the real audit, so here we extract the actual text, headings, tables and
// images and render readable HTML — not a pixel-perfect Office renderer, but the genuine
// document content, with no backend. All extracted text is escaped; images are blob URLs
// we create, so the produced HTML is safe to inject.
const decode = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&')
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const runText = (xml) => decode((xml.match(/<(?:w|a):t[^>]*>([\s\S]*?)<\/(?:w|a):t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join(''))

export async function extractOfficePreview(blob, name) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(blob)
  const ext = (name.split('.').pop() || '').toLowerCase()
  if (ext === 'docx') return docx(zip)
  if (ext === 'pptx') return pptx(zip)
  if (ext === 'xlsx') return xlsx(zip)
  return ''
}

async function docx(zip) {
  if (!zip.file('word/document.xml')) return ''
  const doc = await zip.file('word/document.xml').async('string')
  // resolve embedded images (rId → media blob URL)
  const imgUrl = {}
  if (zip.file('word/_rels/document.xml.rels')) {
    const rels = await zip.file('word/_rels/document.xml.rels').async('string')
    for (const m of rels.matchAll(/<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"/g)) {
      const path = 'word/' + m[2].replace(/^\.\.\//, '')
      if (zip.file(path) && /\.(png|jpe?g|gif|bmp)$/i.test(path)) {
        try { imgUrl[m[1]] = URL.createObjectURL(await zip.file(path).async('blob')) } catch { /* skip */ }
      }
    }
  }
  const body = (doc.match(/<w:body>([\s\S]*)<\/w:body>/) || [])[1] || doc
  const blocks = body.match(/<w:p\b[\s\S]*?<\/w:p>|<w:tbl>[\s\S]*?<\/w:tbl>/g) || []
  const out = []
  for (const blk of blocks) {
    if (out.length > 70) break
    if (blk.startsWith('<w:tbl')) {
      const rows = blk.match(/<w:tr\b[\s\S]*?<\/w:tr>/g) || []
      const body2 = rows.slice(0, 14).map((r, ri) => {
        const cells = r.match(/<w:tc>[\s\S]*?<\/w:tc>/g) || []
        const tag = ri === 0 ? 'th' : 'td'
        return '<tr>' + cells.map((c) => `<${tag}>${esc(runText(c))}</${tag}>`).join('') + '</tr>'
      }).join('')
      out.push(`<table class="opt">${body2}</table>`)
      continue
    }
    const img = blk.match(/<a:blip[^>]*r:embed="([^"]+)"/)
    if (img && imgUrl[img[1]]) { out.push(`<img class="opimg" src="${imgUrl[img[1]]}" alt="" />`); continue }
    const txt = runText(blk)
    if (!txt.trim()) continue
    const style = (blk.match(/<w:pStyle w:val="([^"]+)"/) || [])[1] || ''
    if (/^Title/i.test(style)) out.push(`<h2 class="optitle">${esc(txt)}</h2>`)
    else if (/^Heading1/i.test(style)) out.push(`<h3>${esc(txt)}</h3>`)
    else if (/^Heading/i.test(style)) out.push(`<h4>${esc(txt)}</h4>`)
    else out.push(`<p>${esc(txt)}</p>`)
  }
  return `<div class="oppage">${out.join('') || '<p class="opmuted">No readable text content.</p>'}</div>`
}

async function pptx(zip) {
  const slides = Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))
    .sort((a, b) => (+a.match(/\d+/)) - (+b.match(/\d+/)))
  const out = []
  let i = 0
  for (const sn of slides.slice(0, 14)) {
    i++
    const xml = await zip.file(sn).async('string')
    const texts = [...xml.matchAll(/<a:t[^>]*>([\s\S]*?)<\/a:t>/g)].map((m) => decode(m[1].replace(/<[^>]+>/g, ''))).filter((t) => t.trim())
    const title = texts[0] || `Slide ${i}`
    out.push(`<div class="opslide"><div class="opslidenum">Slide ${i}</div><h4>${esc(title)}</h4>${texts.slice(1).map((t) => `<p>${esc(t)}</p>`).join('')}</div>`)
  }
  return `<div class="oppage ppt">${out.join('') || '<p class="opmuted">No slide text.</p>'}</div>`
}

async function xlsx(zip) {
  let shared = []
  if (zip.file('xl/sharedStrings.xml')) {
    const ss = await zip.file('xl/sharedStrings.xml').async('string')
    shared = [...ss.matchAll(/<si>([\s\S]*?)<\/si>/g)].map((m) => decode((m[1].match(/<t[^>]*>([\s\S]*?)<\/t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join('')))
  }
  const name = Object.keys(zip.files).filter((n) => /^xl\/worksheets\/sheet\d+\.xml$/.test(n)).sort()[0]
  if (!name) return ''
  const xml = await zip.file(name).async('string')
  const rows = xml.match(/<row\b[\s\S]*?<\/row>/g) || []
  const body = rows.slice(0, 24).map((r, ri) => {
    const cells = r.match(/<c\b[\s\S]*?(?:\/>|<\/c>)/g) || []
    const tag = ri === 0 ? 'th' : 'td'
    return '<tr>' + cells.slice(0, 12).map((c) => {
      const v = (c.match(/<v>([\s\S]*?)<\/v>/) || [])[1]
      const txt = v == null ? '' : (/t="s"/.test(c) ? (shared[+v] ?? '') : v)
      return `<${tag}>${esc(txt)}</${tag}>`
    }).join('') + '</tr>'
  }).join('')
  return `<div class="oppage xls"><table class="opt">${body || ''}</table></div>`
}
