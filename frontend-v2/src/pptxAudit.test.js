import { describe, it, expect } from 'vitest'
import JSZip from 'jszip'
import { auditPptx, remediatePptx } from './pptxAudit.js'

// ── Fixture builders ───────────────────────────────────────────────────────────

const SLIDE_IMG_NO_ALT = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:pic>
      <p:nvPicPr>
        <p:cNvPr id="3" name="Chart1"/>
        <p:cNvPicPr/><p:nvPr/>
      </p:nvPicPr>
      <p:blipFill><a:blip r:embed="rId1"/></p:blipFill>
      <p:spPr/>
    </p:pic>
  </p:spTree></p:cSld>
</p:sld>`

const SLIDE_IMG_WITH_ALT = SLIDE_IMG_NO_ALT.replace('id="3" name="Chart1"', 'id="3" name="Chart1" descr="Q3 revenue bar chart"')

const SLIDE_WITH_TITLE = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="1" name="Title 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
        <p:nvPr><p:ph type="title"/></p:nvPr>
      </p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Slide Title</a:t></a:r></a:p></p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
</p:sld>`

const PRES_NO_LANG = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:sldMasterIdLst/><p:sldSz cx="9144000" cy="5143500"/><p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>`

const PRES_WITH_LANG = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xml:lang="en-US">
  <p:sldMasterIdLst/><p:sldSz cx="9144000" cy="5143500"/><p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>`

const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>`

async function makePptx({ slideXml = SLIDE_IMG_NO_ALT, presXml = PRES_NO_LANG } = {}) {
  const z = new JSZip()
  z.file('[Content_Types].xml', CONTENT_TYPES)
  z.file('ppt/presentation.xml', presXml)
  z.file('ppt/slides/slide1.xml', slideXml)
  return z.generateAsync({ type: 'blob' })
}

// ── Detection tests ────────────────────────────────────────────────────────────

describe('pptxAudit — detection', () => {
  it('flags PPTX-ALT-001 when an image has no alt text', async () => {
    const findings = await auditPptx(await makePptx())
    const rules = findings.map((f) => f.rule)
    expect(rules).toContain('PPTX-ALT-001')
    expect(findings.find((f) => f.rule === 'PPTX-ALT-001').detail).toMatch(/1 of 1/)
  })

  it('does NOT flag PPTX-ALT-001 when all images have alt text', async () => {
    const findings = await auditPptx(await makePptx({ slideXml: SLIDE_IMG_WITH_ALT }))
    expect(findings.map((f) => f.rule)).not.toContain('PPTX-ALT-001')
  })

  it('flags PPTX-TITLE-001 when a slide has no title placeholder', async () => {
    const findings = await auditPptx(await makePptx())
    expect(findings.map((f) => f.rule)).toContain('PPTX-TITLE-001')
    expect(findings.find((f) => f.rule === 'PPTX-TITLE-001').detail).toMatch(/#1/)
  })

  it('does NOT flag PPTX-TITLE-001 when the slide has a title placeholder', async () => {
    const findings = await auditPptx(await makePptx({ slideXml: SLIDE_WITH_TITLE }))
    expect(findings.map((f) => f.rule)).not.toContain('PPTX-TITLE-001')
  })

  it('flags PPTX-LANG-001 when presentation has no language', async () => {
    const findings = await auditPptx(await makePptx())
    expect(findings.map((f) => f.rule)).toContain('PPTX-LANG-001')
  })

  it('does NOT flag PPTX-LANG-001 when xml:lang is set', async () => {
    const findings = await auditPptx(await makePptx({ presXml: PRES_WITH_LANG }))
    expect(findings.map((f) => f.rule)).not.toContain('PPTX-LANG-001')
  })
})

// ── Remediation tests ──────────────────────────────────────────────────────────

describe('pptxAudit — remediation', () => {
  it('auto-fixes PPTX-ALT-001 and PPTX-LANG-001 (PPTX-TITLE-001 requires human)', async () => {
    const { blob, changes } = await remediatePptx(await makePptx())
    expect(changes).toEqual(expect.arrayContaining([
      expect.stringContaining('PPTX-ALT-001'),
      expect.stringContaining('PPTX-LANG-001'),
    ]))
    // Re-audit: ALT + LANG should clear; TITLE (no auto-fix) stays
    const after = await auditPptx(blob)
    expect(after.map((f) => f.rule)).not.toContain('PPTX-ALT-001')
    expect(after.map((f) => f.rule)).not.toContain('PPTX-LANG-001')
    expect(after.map((f) => f.rule)).toContain('PPTX-TITLE-001')
  })

  it('applies caller-provided alt text from opts.alts keyed by image name', async () => {
    const { blob } = await remediatePptx(await makePptx(), { alts: { Chart1: 'Q3 revenue bar chart' } })
    const z = await JSZip.loadAsync(blob)
    const xml = await z.file('ppt/slides/slide1.xml').async('string')
    expect(xml).toContain('descr="Q3 revenue bar chart"')
  })

  it('does not double-stamp alt text that already has a descr attribute', async () => {
    const { blob } = await remediatePptx(await makePptx({ slideXml: SLIDE_IMG_WITH_ALT }))
    const z = await JSZip.loadAsync(blob)
    const xml = await z.file('ppt/slides/slide1.xml').async('string')
    // Should still have the original description unchanged
    expect(xml).toContain('descr="Q3 revenue bar chart"')
    // And only one descr per element
    expect((xml.match(/\bdescr=/g) || []).length).toBe(1)
  })

  it('sets xml:lang on <p:presentation> in ppt/presentation.xml', async () => {
    const { blob } = await remediatePptx(await makePptx())
    const z = await JSZip.loadAsync(blob)
    const xml = await z.file('ppt/presentation.xml').async('string')
    expect(xml).toMatch(/xml:lang="en-US"/)
  })

  it('produces a valid PPTX blob with correct MIME content', async () => {
    const { blob } = await remediatePptx(await makePptx())
    expect(blob.type).toBe('application/vnd.openxmlformats-officedocument.presentationml.presentation')
    const bytes = new Uint8Array(await blob.arrayBuffer())
    // PPTX is a ZIP — starts with PK magic bytes
    expect(bytes[0]).toBe(0x50) // P
    expect(bytes[1]).toBe(0x4B) // K
  })
})
