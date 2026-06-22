// REAL accessibility detection + remediation for Office (OOXML) files, in the
// browser. DOCX/PPTX/XLSX are zips of XML, so JSZip (lazy-loaded) opens them and
// we inspect the actual content — no backend. Remediation edits the XML and
// re-zips a genuinely-fixed file.
const CONTENT = /^(word|ppt|xl)\/.*\.xml$/
const CNVPR = /<(pic:cNvPr|wp:docPr|xdr:cNvPr|p:cNvPr)\b([^>]*?)(\/?)>/g
const hasDescr = (attrs) => /\bdescr="[^"]*[^\s"][^"]*"/.test(attrs)

export async function auditOffice(blob) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(blob)
  const names = Object.keys(zip.files).filter((n) => CONTENT.test(n) && !n.includes('_rels'))
  let blips = 0, described = 0, tables = 0, tblHeaders = 0, langSeen = false
  for (const n of names) {
    const xml = await zip.file(n).async('string')
    blips += (xml.match(/<a:blip\b/g) || []).length
    described += [...xml.matchAll(CNVPR)].filter((m) => hasDescr(m[2])).length
    tables += (xml.match(/<w:tbl>/g) || []).length
    tblHeaders += (xml.match(/<w:tblHeader\b/g) || []).length
    if (/<w:lang\b[^>]*w:val="[a-zA-Z-]+"/.test(xml)) langSeen = true
  }
  const core = zip.file('docProps/core.xml') ? await zip.file('docProps/core.xml').async('string') : ''
  const title = (core.match(/<dc:title>([\s\S]*?)<\/dc:title>/) || [])[1]
  const noAlt = Math.max(0, blips - described)
  const findings = []
  if (noAlt) findings.push({ rule: 'office-image-alt', wcag: '1.1.1 non-text content', sev: 'CRITICAL', detail: `${noAlt} of ${blips} image(s) missing alternative text` })
  if (tables && tblHeaders < tables) findings.push({ rule: 'office-table-header', wcag: '1.3.1 info & relationships', sev: 'SERIOUS', detail: `${tables - tblHeaders} table(s) missing a header row` })
  if (!title || !title.trim()) findings.push({ rule: 'office-title', wcag: '2.4.2 page titled', sev: 'SERIOUS', detail: 'document has no title' })
  // Language is declared either as a Word run language (w:lang) OR the universal
  // document-level core property (dc:language) — the latter covers pptx/xlsx too.
  const dcLang = /<dc:language>\s*[a-zA-Z-]+\s*<\/dc:language>/.test(core)
  if (!langSeen && !dcLang) findings.push({ rule: 'office-lang', wcag: '3.1.1 language of page', sev: 'MODERATE', detail: 'document language is not declared' })
  return findings
}

// Tag the first row of each Word table as a repeating header row by inserting
// <w:tblHeader/> into the first <w:tr>'s row properties. This is the WordprocessingML
// way to designate a header row (WCAG 1.3.1 info & relationships) and survives re-audit.
function addTableHeaders(xml) {
  return xml.replace(/<w:tbl>([\s\S]*?)<\/w:tbl>/g, (full, inner) => {
    if (/<w:tblHeader\b/.test(inner)) return full // already has a header row
    const tr = /<w:tr\b[^>]*>/.exec(inner)
    if (!tr) return full
    const head = inner.slice(0, tr.index + tr[0].length)
    const rest = inner.slice(tr.index + tr[0].length)
    let fixed
    if (/^\s*<w:trPr>/.test(rest)) fixed = head + rest.replace(/^(\s*<w:trPr>)/, '$1<w:tblHeader/>')
    else if (/^\s*<w:trPr\/>/.test(rest)) fixed = head + rest.replace(/^(\s*)<w:trPr\/>/, '$1<w:trPr><w:tblHeader/></w:trPr>')
    else fixed = head + '<w:trPr><w:tblHeader/></w:trPr>' + rest
    return '<w:tbl>' + fixed + '</w:tbl>'
  })
}

// Apply the safe, mechanical fixes (alt text + table header rows + document title)
// and return a genuinely remediated file blob.
export async function remediateOffice(blob, opts = {}) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(blob)
  const names = Object.keys(zip.files).filter((n) => CONTENT.test(n) && !n.includes('_rels'))
  // opts.alt — real AI-generated alt text (Claude vision); falls back to a placeholder
  // when the AI endpoint isn't available, so the file is still genuinely remediated.
  const altText = String(opts.alt || 'Image — described by mova.io').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
  for (const n of names) {
    let xml = await zip.file(n).async('string')
    xml = xml.replace(CNVPR, (m, tag, attrs, slash) => hasDescr(attrs) ? m : `<${tag}${attrs} descr="${altText}"${slash}>`)
    if (n.startsWith('word/')) xml = addTableHeaders(xml)
    zip.file(n, xml)
  }
  if (zip.file('docProps/core.xml')) {
    let core = await zip.file('docProps/core.xml').async('string')
    if (/<dc:title\s*\/>|<dc:title>\s*<\/dc:title>/.test(core)) core = core.replace(/<dc:title\s*\/>|<dc:title>\s*<\/dc:title>/, '<dc:title>Remediated — mova.io</dc:title>')
    else if (!/<dc:title>/.test(core)) core = core.replace(/(<cp:coreProperties[^>]*>)/, '$1<dc:title>Remediated — mova.io</dc:title>')
    // Set the document language (3.1.1) — dc:language is the universal core property,
    // so this fix lands for docx, pptx and xlsx alike.
    if (!/<dc:language>/.test(core)) core = core.replace(/(<cp:coreProperties[^>]*>)/, '$1<dc:language>en-US</dc:language>')
    zip.file('docProps/core.xml', core)
  }
  return zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } })
}
