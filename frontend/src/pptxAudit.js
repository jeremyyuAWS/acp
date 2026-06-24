// PPTX accessibility audit + remediation engine.
// Detects and fixes WCAG 2.1 AA issues specific to PowerPoint OOXML structure.
// Rules: PPTX-ALT-001 (1.1.1), PPTX-TITLE-001 (2.4.2), PPTX-LANG-001 (3.1.1)

const NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const NS_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'

const slideNum = (path) => parseInt((path.match(/slide(\d+)\.xml$/) || [])[1] || '0', 10)

// Returns true if a <p:cNvPr> string has meaningful alt text (non-empty descr).
function hasAlt(cNvPrStr) {
  const m = cNvPrStr.match(/\bdescr="([^"]*)"/)
  return m !== null && m[1].trim() !== ''
}

// ── Audit ──────────────────────────────────────────────────────────────────────

export async function auditPptx(file) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(file)
  const findings = []

  // PPTX-LANG-001: presentation-level language not declared
  const presXml = zip.file('ppt/presentation.xml')
    ? await zip.file('ppt/presentation.xml').async('string')
    : ''
  const hasLang = /\bxml:lang=/.test(presXml) || /<a:defRPr[^>]*\blang=/.test(presXml)
  if (!hasLang) {
    findings.push({
      rule: 'PPTX-LANG-001',
      wcag: '3.1.1 language of page',
      sev: 'MODERATE',
      detail: 'Presentation default language is not declared — assistive technology cannot switch pronunciation engine automatically',
    })
  }

  // Per-slide rules
  const slideFiles = Object.keys(zip.files)
    .filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))
    .sort((a, b) => slideNum(a) - slideNum(b))

  let imagesTotal = 0
  let imagesMissingAlt = 0
  const slidesMissingTitle = []

  for (const slidePath of slideFiles) {
    const xml = await zip.file(slidePath).async('string')
    const num = slideNum(slidePath)

    // PPTX-ALT-001: images without alt text
    // Match every <p:pic> block and check its <p:cNvPr>
    const picBlocks = xml.match(/<p:pic\b[\s\S]*?<\/p:pic>/g) || []
    for (const pic of picBlocks) {
      imagesTotal++
      const cNvPrMatch = pic.match(/<p:cNvPr\b[^>]*?\/?>/)?.[0] || ''
      if (!hasAlt(cNvPrMatch)) imagesMissingAlt++
    }

    // PPTX-TITLE-001: slide missing a title placeholder
    // A title or centred-title placeholder gives the slide an accessible name.
    const hasTitlePh = /<p:ph\b[^>]*type="(?:title|ctrTitle)"/.test(xml)
    if (!hasTitlePh) slidesMissingTitle.push(num)
  }

  if (imagesTotal > 0 && imagesMissingAlt > 0) {
    findings.push({
      rule: 'PPTX-ALT-001',
      wcag: '1.1.1 non-text content',
      sev: 'CRITICAL',
      detail: `${imagesMissingAlt} of ${imagesTotal} image(s) missing alt text across slides`,
    })
  }

  if (slidesMissingTitle.length > 0) {
    findings.push({
      rule: 'PPTX-TITLE-001',
      wcag: '2.4.2 page titled',
      sev: 'SERIOUS',
      detail: `${slidesMissingTitle.length} slide(s) without a title placeholder (#${slidesMissingTitle.join(', ')})`,
    })
  }

  return findings
}

// ── Remediation ────────────────────────────────────────────────────────────────

export async function remediatePptx(file, opts = {}) {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(file)
  const changes = []

  // PPTX-LANG-001: set xml:lang on <p:presentation> and add lang to defaultTextStyle
  if (zip.file('ppt/presentation.xml')) {
    let presXml = await zip.file('ppt/presentation.xml').async('string')
    const hasLang = /\bxml:lang=/.test(presXml) || /<a:defRPr[^>]*\blang=/.test(presXml)
    if (!hasLang) {
      // Stamp xml:lang on the root element
      presXml = presXml.replace(/(<p:presentation\b)/, '$1 xml:lang="en-US"')
      // Inject or patch <a:defRPr> inside <p:defaultTextStyle>
      if (/<p:defaultTextStyle>/.test(presXml)) {
        if (/<a:defRPr\b/.test(presXml)) {
          presXml = presXml.replace(/<a:defRPr\b/, '<a:defRPr lang="en-US"')
        } else {
          presXml = presXml.replace(
            '<p:defaultTextStyle>',
            '<p:defaultTextStyle><a:defRPr lang="en-US"/>'
          )
        }
      } else {
        // No defaultTextStyle — append one before </p:presentation>
        presXml = presXml.replace(
          '</p:presentation>',
          `<p:defaultTextStyle><a:defRPr lang="en-US"/></p:defaultTextStyle></p:presentation>`
        )
      }
      zip.file('ppt/presentation.xml', presXml)
      changes.push('PPTX-LANG-001: set presentation language to en-US')
    }
  }

  // PPTX-ALT-001: add alt text to images missing a descr attribute
  const slideFiles = Object.keys(zip.files)
    .filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))
    .sort((a, b) => slideNum(a) - slideNum(b))

  let altCount = 0

  for (const slidePath of slideFiles) {
    let xml = await zip.file(slidePath).async('string')
    let changed = false

    // Process each <p:pic> block independently to avoid cross-block regex bleed
    xml = xml.replace(/<p:pic\b[\s\S]*?<\/p:pic>/g, (picBlock) => {
      return picBlock.replace(/(<p:cNvPr\b)([^>]*?)(\/?>)/, (m, tag, attrs, end) => {
        if (/\bdescr=/.test(attrs)) return m
        const name = (attrs.match(/\bname="([^"]*)"/) || [])[1] || 'Image'
        const alt = (opts.alts && opts.alts[name]) || '[Image — add description]'
        altCount++
        changed = true
        return `${tag}${attrs} descr="${alt}"${end}`
      })
    })

    if (changed) zip.file(slidePath, xml)
  }

  if (altCount > 0) changes.push(`PPTX-ALT-001: stamped alt text on ${altCount} image(s)`)

  const blob = await zip.generateAsync({
    type: 'blob',
    mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  })
  return { blob, changes }
}
