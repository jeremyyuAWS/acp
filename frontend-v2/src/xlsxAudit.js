// XLSX accessibility audit + remediation engine.
// Detects and fixes WCAG 2.1 AA issues specific to Excel OOXML structure.
// Rules: XLSX-TITLE-001 (2.4.2), XLSX-SHEET-001 (2.4.2), XLSX-HEADER-001 (1.3.1), XLSX-ALT-001 (1.1.1)

const GENERIC_NAME_RE = /^Sheet\s*\d*$|^Tab\s*\d*$|^Worksheet\s*\d*$/i

// ── Audit ──────────────────────────────────────────────────────────────────────

export async function auditXlsx(file) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(file)
  const findings = []

  // XLSX-TITLE-001: workbook has no document title
  const core = zip.file('docProps/core.xml')
    ? await zip.file('docProps/core.xml').async('string')
    : ''
  const titleMatch = core.match(/<dc:title\b[^>]*>([\s\S]*?)<\/dc:title>/)
  const hasTitle = titleMatch && titleMatch[1].trim().length > 0
  if (!hasTitle) {
    findings.push({
      rule: 'XLSX-TITLE-001',
      wcag: '2.4.2 page titled',
      sev: 'SERIOUS',
      detail: 'workbook has no title — screen readers announce the raw filename',
    })
  }

  // XLSX-SHEET-001: sheets with generic names
  const wbXml = zip.file('xl/workbook.xml')
    ? await zip.file('xl/workbook.xml').async('string')
    : ''
  const visibleSheets = [...wbXml.matchAll(/<sheet\b([^>]*)(?:\/)?>|<sheet\b([^>]*)><\/sheet>/g)]
    .map((m) => {
      const attrs = m[1] || m[2] || ''
      const nameM = attrs.match(/\bname="([^"]*)"/)
      const stateM = attrs.match(/\bstate="([^"]*)"/)
      return { name: nameM?.[1] || '', state: stateM?.[1] || 'visible' }
    })
    .filter((s) => s.state !== 'hidden' && s.state !== 'veryHidden')

  const genericSheets = visibleSheets.filter((s) => GENERIC_NAME_RE.test(s.name))
  if (genericSheets.length > 0) {
    findings.push({
      rule: 'XLSX-SHEET-001',
      wcag: '2.4.2 page titled',
      sev: 'MODERATE',
      detail: `${genericSheets.length} sheet(s) have generic names (${genericSheets.map((s) => `"${s.name}"`).join(', ')}) — purpose is not programmatically determinable`,
    })
  }

  // XLSX-HEADER-001: worksheets with 2+ data rows but no formal Excel Table structure
  const wsFiles = Object.keys(zip.files).filter((n) => /^xl\/worksheets\/sheet\d+\.xml$/.test(n))
  let unstructuredSheets = 0
  for (const wsPath of wsFiles) {
    const wsXml = await zip.file(wsPath).async('string')
    const rowCount = (wsXml.match(/<row\b/g) || []).length
    const hasTables = /<tableParts\b/.test(wsXml)
    if (rowCount >= 2 && !hasTables) unstructuredSheets++
  }
  if (unstructuredSheets > 0) {
    findings.push({
      rule: 'XLSX-HEADER-001',
      wcag: '1.3.1 info & relationships',
      sev: 'MODERATE',
      detail: `${unstructuredSheets} sheet(s) contain data without a formal Excel Table — header context is not programmatically determinable`,
    })
  }

  // XLSX-ALT-001: images / charts missing alt text
  const drawingFiles = Object.keys(zip.files).filter(
    (n) => /^xl\/drawings\/drawing\d+\.xml$/.test(n),
  )
  let totalBlips = 0
  let missingAlt = 0
  for (const drPath of drawingFiles) {
    const drXml = await zip.file(drPath).async('string')
    for (const m of drXml.matchAll(/<xdr:cNvPr\b([^>]*?)\/?>/g)) {
      totalBlips++
      const descrM = m[1].match(/\bdescr="([^"]*)"/)
      if (!descrM || descrM[1].trim() === '') missingAlt++
    }
  }
  if (totalBlips > 0 && missingAlt > 0) {
    findings.push({
      rule: 'XLSX-ALT-001',
      wcag: '1.1.1 non-text content',
      sev: 'CRITICAL',
      detail: `${missingAlt} of ${totalBlips} image/chart(s) missing alt text — blind users receive nothing`,
    })
  }

  return findings
}

// ── Remediation ────────────────────────────────────────────────────────────────

const escXml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

export async function remediateXlsx(file, opts = {}) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(file)
  const changes = []

  // XLSX-TITLE-001: add/update title in docProps/core.xml
  if (zip.file('docProps/core.xml')) {
    let core = await zip.file('docProps/core.xml').async('string')
    const titleMatch = core.match(/<dc:title\b[^>]*>([\s\S]*?)<\/dc:title>/)
    const hasTitle = titleMatch && titleMatch[1].trim().length > 0
    if (!hasTitle) {
      const title = opts.title || 'Accessible Workbook'
      const escaped = escXml(title)
      if (titleMatch) {
        // Replace empty existing <dc:title> element
        core = core.replace(/<dc:title\b[^>]*>[\s\S]*?<\/dc:title>/, `<dc:title>${escaped}</dc:title>`)
      } else if (/<dc:creator/.test(core)) {
        core = core.replace(
          /(<\/dc:creator>)/,
          `$1<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">${escaped}</dc:title>`,
        )
      } else {
        core = core.replace(
          '</cp:coreProperties>',
          `<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">${escaped}</dc:title></cp:coreProperties>`,
        )
      }
      zip.file('docProps/core.xml', core)
      changes.push('XLSX-TITLE-001: added workbook title')
    }
  }

  // XLSX-ALT-001: stamp alt text on images/charts missing descr
  const drawingFiles = Object.keys(zip.files).filter(
    (n) => /^xl\/drawings\/drawing\d+\.xml$/.test(n),
  )
  let altCount = 0
  for (const drPath of drawingFiles) {
    let drXml = await zip.file(drPath).async('string')
    let changed = false
    drXml = drXml.replace(/<xdr:cNvPr\b([^>]*?)(\/?>)/g, (m, attrs, end) => {
      const descrM = attrs.match(/\bdescr="([^"]*)"/)
      if (descrM && descrM[1].trim() !== '') return m
      const nameM = attrs.match(/\bname="([^"]*)"/)
      const label = nameM?.[1] || 'Chart'
      const alt = (opts.alts && opts.alts[label]) || `[${label} — add description]`
      altCount++
      changed = true
      if (/\bdescr=/.test(attrs)) {
        return `<xdr:cNvPr ${attrs.replace(/\bdescr="[^"]*"/, `descr="${escXml(alt)}"`)}`+ end
      }
      return `<xdr:cNvPr${attrs} descr="${escXml(alt)}"${end}`
    })
    if (changed) zip.file(drPath, drXml)
  }
  if (altCount > 0) changes.push(`XLSX-ALT-001: stamped alt text on ${altCount} image/chart(s)`)

  const blob = await zip.generateAsync({
    type: 'blob',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  return { blob, changes }
}
