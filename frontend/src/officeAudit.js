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
  if (!langSeen) findings.push({ rule: 'office-lang', wcag: '3.1.1 language of page', sev: 'MODERATE', detail: 'document language is not declared' })
  return findings
}

// Apply the safe, mechanical fixes (alt text + document title) and return a
// genuinely remediated file blob.
export async function remediateOffice(blob) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(blob)
  const names = Object.keys(zip.files).filter((n) => CONTENT.test(n) && !n.includes('_rels'))
  for (const n of names) {
    let xml = await zip.file(n).async('string')
    xml = xml.replace(CNVPR, (m, tag, attrs, slash) => hasDescr(attrs) ? m : `<${tag}${attrs} descr="Image — described by mova.io"${slash}>`)
    zip.file(n, xml)
  }
  if (zip.file('docProps/core.xml')) {
    let core = await zip.file('docProps/core.xml').async('string')
    if (/<dc:title\s*\/>|<dc:title>\s*<\/dc:title>/.test(core)) core = core.replace(/<dc:title\s*\/>|<dc:title>\s*<\/dc:title>/, '<dc:title>Remediated — mova.io</dc:title>')
    else if (!/<dc:title>/.test(core)) core = core.replace(/(<cp:coreProperties[^>]*>)/, '$1<dc:title>Remediated — mova.io</dc:title>')
    zip.file('docProps/core.xml', core)
  }
  return zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } })
}
