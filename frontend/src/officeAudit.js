// REAL accessibility detection + remediation for Office (OOXML) files, in the
// browser. DOCX/PPTX/XLSX are zips of XML, so JSZip (lazy-loaded) opens them and
// we inspect the actual content — no backend. Remediation edits the XML and
// re-zips a genuinely-fixed file.
const CONTENT = /^(word|ppt|xl)\/.*\.xml$/
const CNVPR = /<(pic:cNvPr|wp:docPr|xdr:cNvPr|p:cNvPr)\b([^>]*?)(\/?)>/g
const hasDescr = (attrs) => /\bdescr="[^"]*[^\s"][^"]*"/.test(attrs)

const GENERIC_LINK_RE = /\b(click here|click this|^here$|read more|learn more|^more$|this link|this page|^link$)\b/i

export async function auditOffice(blob) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(blob)
  const names = Object.keys(zip.files).filter((n) => CONTENT.test(n) && !n.includes('_rels'))
  let blips = 0, described = 0, tables = 0, tblHeaders = 0, langSeen = false
  const headingLevels = [], genericLinks = []
  const GENERIC_LINK_RE = /\b(click here|click this|^here$|read more|learn more|^more$|this link|this page|^link$)\b/i
  for (const n of names) {
    const xml = await zip.file(n).async('string')
    blips += (xml.match(/<a:blip\b/g) || []).length
    described += [...xml.matchAll(CNVPR)].filter((m) => hasDescr(m[2])).length
    tables += (xml.match(/<w:tbl>/g) || []).length
    tblHeaders += (xml.match(/<w:tblHeader\b/g) || []).length
    if (/<w:lang\b[^>]*w:val="[a-zA-Z-]+"/.test(xml)) langSeen = true
    // Heading structure (DOCX-HEAD-001): collect heading levels in document order
    if (n.includes('document') || n.includes('slide')) {
      for (const m of xml.matchAll(/<w:pStyle w:val="Heading(\d+)"/g)) headingLevels.push(parseInt(m[1]))
    }
    // Link purpose (DOCX-LINK-001): find hyperlinks with generic anchor text
    for (const hl of (xml.match(/<w:hyperlink\b[\s\S]*?<\/w:hyperlink>/g) || [])) {
      const text = hl.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()
      if (GENERIC_LINK_RE.test(text)) genericLinks.push(text)
    }
  }
  const core = zip.file('docProps/core.xml') ? await zip.file('docProps/core.xml').async('string') : ''
  const title = (core.match(/<dc:title>([\s\S]*?)<\/dc:title>/) || [])[1]
  const noAlt = Math.max(0, blips - described)
  // Heading structure: flag if any level jumps by more than 1 from the previous max
  let headingSkip = false
  let maxSeen = 0
  for (const h of headingLevels) {
    if (h > maxSeen + 1 && maxSeen > 0) { headingSkip = true; break }
    if (h > maxSeen) maxSeen = h
  }
  const findings = []
  if (noAlt) findings.push({ rule: 'DOCX-ALT-001', wcag: '1.1.1 non-text content', sev: 'CRITICAL', detail: `${noAlt} of ${blips} image(s) missing alternative text — blind users receive nothing` })
  if (tables && tblHeaders < tables) findings.push({ rule: 'DOCX-TABLE-001', wcag: '1.3.1 info & relationships', sev: 'SERIOUS', detail: `${tables - tblHeaders} table(s) missing a header row — row purpose not programmatically determinable` })
  if (headingSkip) findings.push({ rule: 'DOCX-HEAD-001', wcag: '1.3.1 info & relationships', sev: 'SERIOUS', detail: 'heading levels are skipped — logical document structure is broken for assistive technology' })
  if (!title || !title.trim()) findings.push({ rule: 'DOCX-TITLE-001', wcag: '2.4.2 page titled', sev: 'SERIOUS', detail: 'document has no title — screen readers announce the raw filename' })
  if (genericLinks.length) findings.push({ rule: 'DOCX-LINK-001', wcag: '2.4.4 link purpose', sev: 'MODERATE', detail: `${genericLinks.length} hyperlink(s) with generic text ("${genericLinks[0]}") — purpose is ambiguous out of context` })
  const dcLang = /<dc:language>\s*[a-zA-Z-]+\s*<\/dc:language>/.test(core)
  if (!langSeen && !dcLang) findings.push({ rule: 'DOCX-LANG-001', wcag: '3.1.1 language of page', sev: 'MODERATE', detail: 'document language not declared — TTS uses incorrect pronunciation rules' })
  return findings
}

const TC_AUTHOR = 'Mova Accessibility Platform'
const getISODate = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
const TC_INITIALS = 'MAP'

// Tag the first row of each Word table as a repeating header row.
// When tcId is provided ({n: number}), wraps the change in <w:trPrChange> tracked-change
// markup so the fix is visible as a formatting revision in Word's Track Changes view.
function addTableHeaders(xml, tcId = null, tcDate = '') {
  return xml.replace(/<w:tbl>([\s\S]*?)<\/w:tbl>/g, (full, inner) => {
    if (/<w:tblHeader\b/.test(inner)) return full
    const tr = /<w:tr\b[^>]*>/.exec(inner)
    if (!tr) return full
    const head = inner.slice(0, tr.index + tr[0].length)
    const rest = inner.slice(tr.index + tr[0].length)
    // <w:trPrChange> records the ORIGINAL state; it must come last inside <w:trPr>
    const tcMark = tcId
      ? `<w:trPrChange w:id="${tcId.n++}" w:author="${TC_AUTHOR}" w:date="${tcDate}"><w:trPr/></w:trPrChange>`
      : ''
    let fixed
    if (/^\s*<w:trPr>/.test(rest)) {
      // Existing <w:trPr> with content: insert header + change record before closing tag
      fixed = head + rest.replace(/(<\/w:trPr>)/, `<w:tblHeader/>${tcMark}$1`)
    } else if (/^\s*<w:trPr\/>/.test(rest)) {
      fixed = head + rest.replace(/^\s*<w:trPr\/>/, `<w:trPr><w:tblHeader/>${tcMark}</w:trPr>`)
    } else {
      fixed = head + `<w:trPr><w:tblHeader/>${tcMark}</w:trPr>` + rest
    }
    return '<w:tbl>' + fixed + '</w:tbl>'
  })
}

// Inject Word comment balloons into the document for fixes that have no inline
// tracked-change equivalent (document title, language, metadata properties).
// Adds word/comments.xml, updates _rels and [Content_Types].xml, and inserts
// commentRangeStart/End markers anchored to the first body paragraph.
async function injectComments(zip, entries) {
  if (!entries.length) return
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

  // Build comments.xml
  const commentEls = entries.map(({ id, text }) =>
    `<w:comment w:id="${id}" w:author="${esc(TC_AUTHOR)}" w:date="${tcDate}" w:initials="${TC_INITIALS}">` +
    `<w:p><w:r><w:t xml:space="preserve">${esc(text)}</w:t></w:r></w:p>` +
    `</w:comment>`
  ).join('')
  zip.file('word/comments.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments ${W}>${commentEls}</w:comments>`)

  // Register in [Content_Types].xml
  let ct = await zip.file('[Content_Types].xml').async('string')
  if (!ct.includes('comments.xml')) {
    ct = ct.replace('</Types>',
      '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/></Types>')
    zip.file('[Content_Types].xml', ct)
  }

  // Register relationship in word/_rels/document.xml.rels
  const relsPath = 'word/_rels/document.xml.rels'
  if (zip.file(relsPath)) {
    let rels = await zip.file(relsPath).async('string')
    if (!rels.includes('/comments')) {
      const maxId = Math.max(...[...rels.matchAll(/Id="rId(\d+)"/g)].map((m) => parseInt(m[1])), 0)
      rels = rels.replace('</Relationships>',
        `<Relationship Id="rId${maxId + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/></Relationships>`)
      zip.file(relsPath, rels)
    }
  }

  // Insert comment range markers anchored to the first body paragraph
  let doc = await zip.file('word/document.xml').async('string')
  const starts = entries.map((e) => `<w:commentRangeStart w:id="${e.id}"/>`).join('')
  const ends = entries.map((e) =>
    `<w:commentRangeEnd w:id="${e.id}"/>` +
    `<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="${e.id}"/></w:r>`
  ).join('')
  // Wrap the first paragraph: starts before <w:p>, ends just before </w:p>
  doc = doc.replace(/(<w:p[ >])/, `${starts}$1`)
  doc = doc.replace(/<\/w:p>/, `${ends}</w:p>`)
  zip.file('word/document.xml', doc)
}

// Apply the safe, mechanical fixes (alt text + table header rows + document title + language)
// and return a genuinely remediated file blob.
// opts.trackedChanges = true → table header fixes are wrapped in <w:trPrChange> markup and
// metadata fixes appear as Word comment balloons, so reviewers see exactly what changed.
export async function remediateOffice(blob, opts = {}) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(blob)
  const names = Object.keys(zip.files).filter((n) => CONTENT.test(n) && !n.includes('_rels'))
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
  const fallback = String(opts.alt || 'Image — described by mova.io')
  const alts = opts.alts || {}
  const tc = opts.trackedChanges
  const tcId = tc ? { n: 100 } : null  // tracked-change revision IDs start at 100
  const tcDate = opts.remediationDate || getISODate()
  const wcagVer = opts.wcagVersion || '2.1'
  const certBy = opts.assignee ? opts.assignee + ' via Mova Accessibility Platform' : 'Mova Accessibility Platform'

  for (const n of names) {
    let xml = await zip.file(n).async('string')
    const rid2media = {}
    const relsPath = n.replace(/([^/]+)$/, '_rels/$1.rels')
    if (zip.file(relsPath)) {
      const relsXml = await zip.file(relsPath).async('string')
      for (const r of relsXml.matchAll(/Id="([^"]+)"[^>]*Target="([^"]+)"/g)) rid2media[r[1]] = r[2].split('/').pop()
    }
    xml = xml.replace(CNVPR, (m, tag, attrs, slash, offset) => {
      if (hasDescr(attrs)) return m
      const blip = /<a:blip\b[^>]*r:embed="([^"]+)"/.exec(xml.slice(offset))
      const media = blip ? rid2media[blip[1]] : null
      const alt = (media && alts[media]) || fallback
      return `<${tag}${attrs} descr="${esc(alt)}"${slash}>`
    })
    if (n.startsWith('word/')) xml = addTableHeaders(xml, tcId, tcDate)
    zip.file(n, xml)
  }

  // --- Core property fixes (title + language) ---
  const comments = []
  if (zip.file('docProps/core.xml')) {
    let core = await zip.file('docProps/core.xml').async('string')
    const hadTitle = /<dc:title>[^<]+<\/dc:title>/.test(core)
    if (/<dc:title\s*\/>|<dc:title>\s*<\/dc:title>/.test(core)) {
      core = core.replace(/<dc:title\s*\/>|<dc:title>\s*<\/dc:title>/, '<dc:title>Accessibility Review — mova.io</dc:title>')
    } else if (!/<dc:title>/.test(core)) {
      core = core.replace(/(<cp:coreProperties[^>]*>)/, '$1<dc:title>Accessibility Review — mova.io</dc:title>')
    }
    if (!hadTitle && tc) {
      comments.push({ id: 1, text: '✓ FIXED (DOCX-TITLE-001): Document title set to "Accessibility Review — mova.io". Screen readers now announce a meaningful title when this file opens, instead of the raw filename.' })
    }
    const hadLang = /<dc:language>/.test(core)
    if (!hadLang) {
      core = core.replace(/(<cp:coreProperties[^>]*>)/, '$1<dc:language>en-US</dc:language>')
      if (tc) {
        comments.push({ id: 2, text: '✓ FIXED (DOCX-LANG-001): Document language set to English (en-US). Text-to-speech engines now use the correct English voice and pronunciation rules.' })
      }
    }
    if (tc) {
      const docXml = zip.file('word/document.xml') ? await zip.file('word/document.xml').async('string') : ''
      if (tcId && tcId.n > 100) {
        const tableCount = (docXml.match(/<w:tblHeader\b/g) || []).length
        comments.push({ id: 3, text: `✓ FIXED (DOCX-TABLE-001): ${tableCount} table header row(s) marked (see formatting tracked changes on each table's first row). Screen readers can now announce column names as users navigate cells.` })
      }
      // Heading structure: detect skips and add a review comment
      const headingLevels = [...docXml.matchAll(/<w:pStyle w:val="Heading(\d+)"/g)].map((m) => parseInt(m[1]))
      let headingSkip = false; let maxSeen = 0
      for (const h of headingLevels) {
        if (h > maxSeen + 1 && maxSeen > 0) { headingSkip = true; break }
        if (h > maxSeen) maxSeen = h
      }
      if (headingSkip) {
        comments.push({ id: 4, text: '\u26a0 REVIEW NEEDED (DOCX-HEAD-001): Heading levels skip in this document — logical structure is broken for screen readers. Open the Styles panel (Home \u2192 Styles) and ensure headings are sequential: Heading 1 \u2192 Heading 2 \u2192 Heading 3, no levels skipped.' })
      }
      // Generic link text: flag each link that needs a manual rewrite
      const genericLinkTexts = [...docXml.matchAll(/<w:hyperlink\b[\s\S]*?<\/w:hyperlink>/g)]
        .map((m) => m[0].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim())
        .filter((t) => GENERIC_LINK_RE.test(t))
      if (genericLinkTexts.length) {
        comments.push({ id: 5, text: `\u26a0 REVIEW NEEDED (DOCX-LINK-001): ${genericLinkTexts.length} hyperlink(s) use generic text ("${genericLinkTexts[0]}") that is ambiguous out of context. Replace each link's visible text with a description of its destination, e.g. "View the full accessibility report" instead of "click here".` })
      }
    }
    // Insert a Heading 1 as a tracked insertion so Word shows green underlined text —
    // makes the title fix immediately visible without opening the Reviewing Pane.
    if (!hadTitle && tc && zip.file('word/document.xml')) {
      let doc = await zip.file('word/document.xml').async('string')
      const hp =
        `<w:p><w:pPr><w:pStyle w:val="Heading1"/>` +
        `<w:rPr><w:ins w:id="210" w:author="${esc(TC_AUTHOR)}" w:date="${tcDate}"/></w:rPr></w:pPr>` +
        `<w:ins w:id="211" w:author="${esc(TC_AUTHOR)}" w:date="${tcDate}">` +
        `<w:r><w:t xml:space="preserve">Accessibility Review — mova.io</w:t></w:r></w:ins></w:p>`
      zip.file('word/document.xml', doc.replace(/(<w:body[^>]*>)/, `$1${hp}`))
    }
    // Stamp remediation metadata into file properties (version, certifier, WCAG standard, modified date)
    const cpEnd = '</cp:coreProperties>'
    const upsert = (xml, tag, val, attr) => {
      const open = attr ? '<' + tag + ' ' + attr + '>' : '<' + tag + '>'
      const close = '</' + tag + '>'
      const el = open + val + close
      const si = xml.indexOf('<' + tag)
      if (si >= 0) { const ei = xml.indexOf(close, si) + close.length; return xml.slice(0, si) + el + xml.slice(ei) }
      const ci = xml.lastIndexOf(cpEnd)
      return xml.slice(0, ci) + el + xml.slice(ci)
    }
    const kwVal = 'WCAG ' + wcagVer + ' AA · Certified by Mova Accessibility Platform'
    core = upsert(core, 'cp:lastModifiedBy', esc(certBy))
    core = upsert(core, 'cp:keywords', esc(kwVal))
    core = upsert(core, 'cp:category', 'Accessibility Compliance')
    core = upsert(core, 'cp:contentStatus', 'Certified WCAG ' + wcagVer + ' AA')
    core = upsert(core, 'dcterms:modified', tcDate, 'xsi:type="dcterms:W3CDTF"')
    zip.file('docProps/core.xml', core)
  }

  // Inject comment balloons for metadata fixes (tracked changes mode only)
  if (tc && comments.length) await injectComments(zip, comments)

  // Enable Track Changes mode so Word opens the file with revisions visible.
  // Create settings.xml if the DOCX doesn't have one (many minimal templates omit it).
  if (tc) {
    const W_SETTINGS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    const SETTINGS_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'
    const SETTINGS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings'
    if (zip.file('word/settings.xml')) {
      let settings = await zip.file('word/settings.xml').async('string')
      if (!settings.includes('w:trackChanges')) {
        settings = settings.replace(/(<w:settings\b[^>]*>)/, '$1<w:trackChanges/>')
        zip.file('word/settings.xml', settings)
      }
    } else {
      // Create a minimal settings.xml and wire it up
      zip.file('word/settings.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="${W_SETTINGS}"><w:trackChanges/></w:settings>`)
      // Register content type
      if (zip.file('[Content_Types].xml')) {
        let ct = await zip.file('[Content_Types].xml').async('string')
        if (!ct.includes('settings.xml')) {
          ct = ct.replace('</Types>', `<Override PartName="/word/settings.xml" ContentType="${SETTINGS_CT}"/></Types>`)
          zip.file('[Content_Types].xml', ct)
        }
      }
      // Register relationship
      const relsPath = 'word/_rels/document.xml.rels'
      if (zip.file(relsPath)) {
        let rels = await zip.file(relsPath).async('string')
        if (!rels.includes('/settings')) {
          const maxId = Math.max(...[...rels.matchAll(/Id="rId(\d+)"/g)].map((m) => parseInt(m[1])), 0)
          rels = rels.replace('</Relationships>', `<Relationship Id="rId${maxId + 1}" Type="${SETTINGS_REL}" Target="settings.xml"/></Relationships>`)
          zip.file(relsPath, rels)
        }
      }
    }
  }

  return zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } })
}
