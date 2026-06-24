import { describe, it, expect } from 'vitest'
import JSZip from 'jszip'
import { auditXlsx, remediateXlsx } from './xlsxAudit.js'

// ── Fixture builders ───────────────────────────────────────────────────────────

const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
</Types>`

const RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`

const CORE_NO_TITLE = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">
  <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Test User</dc:creator>
</cp:coreProperties>`

const CORE_WITH_TITLE = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">
  <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Q3 Financial Summary</dc:title>
  <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Test User</dc:creator>
</cp:coreProperties>`

const WB_GENERIC_SHEETS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
    <sheet name="Sheet2" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>`

const WB_NAMED_SHEETS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Financial Data" sheetId="1" r:id="rId1"/>
    <sheet name="Chart Summary" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>`

const WB_HIDDEN_GENERIC = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Financial Data" sheetId="1" r:id="rId1"/>
    <sheet name="Sheet2" sheetId="2" state="hidden" r:id="rId2"/>
  </sheets>
</workbook>`

// Sheet with 3 data rows but no tableParts → unstructured
const SHEET_DATA_NO_TABLE = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>Alice</t></is></c></row>
    <row r="3"><c r="A3" t="inlineStr"><is><t>Bob</t></is></c></row>
  </sheetData>
</worksheet>`

// Sheet with tableParts → formally structured
const SHEET_DATA_WITH_TABLE = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
           xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>Alice</t></is></c></row>
  </sheetData>
  <tableParts count="1"><tablePart r:id="rId1"/></tableParts>
</worksheet>`

// Only one row → not flagged (no data rows below header)
const SHEET_ONE_ROW = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c></row>
  </sheetData>
</worksheet>`

const DRAWING_NO_ALT = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">
  <xdr:twoCellAnchor>
    <xdr:graphicFrame>
      <xdr:nvGraphicFramePr>
        <xdr:cNvPr id="2" name="Chart 1"/>
      </xdr:nvGraphicFramePr>
    </xdr:graphicFrame>
  </xdr:twoCellAnchor>
</xdr:wsDr>`

const DRAWING_WITH_ALT = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">
  <xdr:twoCellAnchor>
    <xdr:graphicFrame>
      <xdr:nvGraphicFramePr>
        <xdr:cNvPr id="2" name="Chart 1" descr="Q3 revenue bar chart by region"/>
      </xdr:nvGraphicFramePr>
    </xdr:graphicFrame>
  </xdr:twoCellAnchor>
</xdr:wsDr>`

async function makeXlsx({ core, workbook, sheets = {}, drawings = {} } = {}) {
  const zip = new JSZip()
  zip.file('[Content_Types].xml', CONTENT_TYPES)
  zip.file('_rels/.rels', RELS)
  zip.file('docProps/core.xml', core ?? CORE_NO_TITLE)
  zip.file('xl/workbook.xml', workbook ?? WB_NAMED_SHEETS)
  for (const [name, xml] of Object.entries(sheets)) {
    zip.file(`xl/worksheets/${name}`, xml)
  }
  for (const [name, xml] of Object.entries(drawings)) {
    zip.file(`xl/drawings/${name}`, xml)
  }
  const buf = await zip.generateAsync({ type: 'arraybuffer' })
  return new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
}

// ── Detection tests ────────────────────────────────────────────────────────────

describe('auditXlsx', () => {
  it('XLSX-TITLE-001: flags missing title', async () => {
    const file = await makeXlsx({ core: CORE_NO_TITLE })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-TITLE-001')).toBe(true)
  })

  it('XLSX-TITLE-001: passes when title is present', async () => {
    const file = await makeXlsx({ core: CORE_WITH_TITLE })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-TITLE-001')).toBe(false)
  })

  it('XLSX-SHEET-001: flags generic sheet names', async () => {
    const file = await makeXlsx({ workbook: WB_GENERIC_SHEETS })
    const findings = await auditXlsx(file)
    const f = findings.find((x) => x.rule === 'XLSX-SHEET-001')
    expect(f).toBeDefined()
    expect(f.detail).toMatch(/Sheet1/)
    expect(f.detail).toMatch(/Sheet2/)
  })

  it('XLSX-SHEET-001: passes when sheet names are meaningful', async () => {
    const file = await makeXlsx({ workbook: WB_NAMED_SHEETS })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-SHEET-001')).toBe(false)
  })

  it('XLSX-SHEET-001: ignores hidden sheets with generic names', async () => {
    const file = await makeXlsx({ workbook: WB_HIDDEN_GENERIC })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-SHEET-001')).toBe(false)
  })

  it('XLSX-HEADER-001: flags data rows without table structure', async () => {
    const file = await makeXlsx({ sheets: { 'sheet1.xml': SHEET_DATA_NO_TABLE } })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-HEADER-001')).toBe(true)
  })

  it('XLSX-HEADER-001: passes when tableParts is present', async () => {
    const file = await makeXlsx({ sheets: { 'sheet1.xml': SHEET_DATA_WITH_TABLE } })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-HEADER-001')).toBe(false)
  })

  it('XLSX-HEADER-001: does not flag single-row sheets', async () => {
    const file = await makeXlsx({ sheets: { 'sheet1.xml': SHEET_ONE_ROW } })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-HEADER-001')).toBe(false)
  })

  it('XLSX-ALT-001: flags chart without alt text', async () => {
    const file = await makeXlsx({ drawings: { 'drawing1.xml': DRAWING_NO_ALT } })
    const findings = await auditXlsx(file)
    const f = findings.find((x) => x.rule === 'XLSX-ALT-001')
    expect(f).toBeDefined()
    expect(f.detail).toMatch(/1 of 1/)
  })

  it('XLSX-ALT-001: passes when alt text is present', async () => {
    const file = await makeXlsx({ drawings: { 'drawing1.xml': DRAWING_WITH_ALT } })
    const findings = await auditXlsx(file)
    expect(findings.some((f) => f.rule === 'XLSX-ALT-001')).toBe(false)
  })
})

// ── Remediation tests ──────────────────────────────────────────────────────────

describe('remediateXlsx', () => {
  it('XLSX-TITLE-001: adds title to core.xml', async () => {
    const file = await makeXlsx({ core: CORE_NO_TITLE })
    const { blob, changes } = await remediateXlsx(file, { title: 'Q4 Report' })
    expect(changes.some((c) => c.includes('XLSX-TITLE-001'))).toBe(true)
    const zip2 = await JSZip.loadAsync(blob)
    const core2 = await zip2.file('docProps/core.xml').async('string')
    expect(core2).toMatch(/<dc:title[^>]*>Q4 Report<\/dc:title>/)
  })

  it('XLSX-TITLE-001: re-audit clears the finding after fix', async () => {
    const file = await makeXlsx({ core: CORE_NO_TITLE })
    const { blob } = await remediateXlsx(file, { title: 'Fixed Workbook' })
    const findings = await auditXlsx(blob)
    expect(findings.some((f) => f.rule === 'XLSX-TITLE-001')).toBe(false)
  })

  it('XLSX-ALT-001: stamps alt text on charts missing descr', async () => {
    const file = await makeXlsx({ drawings: { 'drawing1.xml': DRAWING_NO_ALT } })
    const { blob, changes } = await remediateXlsx(file)
    expect(changes.some((c) => c.includes('XLSX-ALT-001'))).toBe(true)
    const zip2 = await JSZip.loadAsync(blob)
    const dr2 = await zip2.file('xl/drawings/drawing1.xml').async('string')
    expect(dr2).toMatch(/descr="[^"]+[^\s"]+[^"]*"/)
  })

  it('XLSX-ALT-001: re-audit clears the finding after fix', async () => {
    const file = await makeXlsx({ drawings: { 'drawing1.xml': DRAWING_NO_ALT } })
    const { blob } = await remediateXlsx(file)
    const findings = await auditXlsx(blob)
    expect(findings.some((f) => f.rule === 'XLSX-ALT-001')).toBe(false)
  })

  it('XLSX-ALT-001: preserves existing alt text', async () => {
    const file = await makeXlsx({ drawings: { 'drawing1.xml': DRAWING_WITH_ALT } })
    const { blob, changes } = await remediateXlsx(file)
    expect(changes.some((c) => c.includes('XLSX-ALT-001'))).toBe(false)
    const zip2 = await JSZip.loadAsync(blob)
    const dr2 = await zip2.file('xl/drawings/drawing1.xml').async('string')
    expect(dr2).toMatch(/descr="Q3 revenue bar chart by region"/)
  })
})
