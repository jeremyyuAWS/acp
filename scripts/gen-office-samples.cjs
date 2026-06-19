#!/usr/bin/env node
/*
 * Regenerates the Office demo samples for the Upload tab with deliberate, OBVIOUS
 * accessibility issues so the in-browser before→after is memorable:
 *   benefits-policy.docx  — 2 images (no alt) + a data table (no header row) + no title
 *   finance-metrics.xlsx  — a data table + an un-alt'd chart image + no title
 * These are processed by the REAL in-browser engine (officeAudit/officePreview/
 * remediateOffice), so the fixes shown are genuine. No new deps — uses the app's JSZip.
 * Run: node scripts/gen-office-samples.cjs
 */
const fs = require('fs')
const path = require('path')
const JSZip = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'jszip'))

const SAMPLES = path.join(__dirname, '..', 'frontend', 'public', 'samples')
const img = fs.readFileSync(path.join(SAMPLES, 'sample-image.png'))
const xml = (s) => '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + s

// ---- DOCX ----
const drawing = (rid, id, name) => `<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">` +
  `<wp:extent cx="3200400" cy="1828800"/><wp:effectExtent l="0" t="0" r="0" b="0"/>` +
  `<wp:docPr id="${id}" name="${name}"/>` +
  `<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">` +
  `<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="${id}" name="${name}"/><pic:cNvPicPr/></pic:nvPicPr>` +
  `<pic:blipFill><a:blip r:embed="${rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>` +
  `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3200400" cy="1828800"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>` +
  `</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>`
const para = (t, style) => `<w:p>${style ? `<w:pPr><w:pStyle w:val="${style}"/></w:pPr>` : ''}<w:r><w:t xml:space="preserve">${t}</w:t></w:r></w:p>`
const cell = (t) => `<w:tc><w:tcPr><w:tcW w:w="2160" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>${t}</w:t></w:r></w:p></w:tc>`
const row = (cells) => `<w:tr>${cells.map(cell).join('')}</w:tr>`
const table = `<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:tblBorders></w:tblPr>` +
  [['Region', 'Enrolled', 'Eligible', 'Rate'], ['West', '4,820', '6,100', '79%'], ['Northeast', '3,240', '4,500', '72%'], ['South', '2,910', '3,800', '77%'], ['Midwest', '1,760', '2,300', '77%']].map(row).join('') + `</w:tbl>`

const documentXml = xml(
  `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>` +
  para('Employee Benefits Policy 2026', 'Heading1') +
  para('This guide summarizes medical, dental, and retirement benefits for all UT Southwestern employees for the 2026 plan year. Open enrollment runs March 1–31.') +
  para('Enrollment by region', 'Heading2') +
  drawing('rId1', 2, 'Enrollment chart') +
  para('Figure 1. Q3 benefits enrollment by region.') +
  table +
  para('Plan tiers', 'Heading2') +
  para('Three medical tiers are available: Core, Plus, and Premier. See the comparison below.') +
  drawing('rId2', 3, 'Plan comparison chart') +
  para('Figure 2. Premium comparison across the three plan tiers.') +
  para('Questions? Contact the Benefits Office at benefits@utsouthwestern.edu.') +
  `<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>` +
  `</w:body></w:document>`)

async function buildDocx() {
  const z = new JSZip()
  z.file('[Content_Types].xml', xml(`<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>`))
  z.file('_rels/.rels', xml(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>`))
  // NOTE: no <dc:title> on purpose → "no document title" finding.
  z.file('docProps/core.xml', xml(`<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>UT Southwestern HR</dc:creator></cp:coreProperties>`))
  z.file('word/document.xml', documentXml)
  z.file('word/_rels/document.xml.rels', xml(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image2.png"/></Relationships>`))
  z.file('word/media/image1.png', img)
  z.file('word/media/image2.png', img)
  const buf = await z.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })
  fs.writeFileSync(path.join(SAMPLES, 'benefits-policy.docx'), buf)
  console.log('wrote benefits-policy.docx', buf.length, 'bytes')
}

// ---- XLSX ----
const sst = ['Q3 Benefits Enrollment', 'Region', 'Enrolled', 'Eligible', 'Rate', 'West', 'Northeast', 'South', 'Midwest', 'Total']
const si = (i) => `<c r="${i}" t="s"><v>${i}</v></c>` // placeholder, replaced below
function cellRef(col, rowN) { return String.fromCharCode(65 + col) + rowN }
function sRow(rowN, vals) {
  return `<row r="${rowN}">` + vals.map((v, c) => {
    const ref = cellRef(c, rowN)
    if (typeof v === 'number') return `<c r="${ref}"><v>${v}</v></c>`
    const idx = sst.indexOf(v)
    return `<c r="${ref}" t="s"><v>${idx}</v></c>`
  }).join('') + `</row>`
}
const sheetData = [
  sRow(1, ['Region', 'Enrolled', 'Eligible', 'Rate']),
  sRow(2, ['West', 4820, 6100, 0.79]),
  sRow(3, ['Northeast', 3240, 4500, 0.72]),
  sRow(4, ['South', 2910, 3800, 0.77]),
  sRow(5, ['Midwest', 1760, 2300, 0.77]),
].join('')

async function buildXlsx() {
  const z = new JSZip()
  z.file('[Content_Types].xml', xml(`<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/><Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>`))
  z.file('_rels/.rels', xml(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>`))
  z.file('docProps/core.xml', xml(`<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Finance</dc:creator></cp:coreProperties>`))
  z.file('xl/workbook.xml', xml(`<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Enrollment" sheetId="1" r:id="rId1"/></sheets></workbook>`))
  z.file('xl/_rels/workbook.xml.rels', xml(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>`))
  z.file('xl/sharedStrings.xml', xml(`<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="${sst.length}" uniqueCount="${sst.length}">${sst.map((s) => `<si><t>${s}</t></si>`).join('')}</sst>`))
  z.file('xl/worksheets/sheet1.xml', xml(`<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData>${sheetData}</sheetData><drawing r:id="rId1"/></worksheet>`))
  z.file('xl/worksheets/_rels/sheet1.xml.rels', xml(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>`))
  // Floating chart image with NO descr (alt) → "image missing alt" finding.
  z.file('xl/drawings/drawing1.xml', xml(`<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><xdr:twoCellAnchor editAs="oneCell"><xdr:from><xdr:col>5</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to><xdr:col>11</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>16</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="Enrollment chart"/><xdr:cNvPicPr/></xdr:nvPicPr><xdr:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:twoCellAnchor></xdr:wsDr>`))
  z.file('xl/drawings/_rels/drawing1.xml.rels', xml(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/></Relationships>`))
  z.file('xl/media/image1.png', img)
  const buf = await z.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })
  fs.writeFileSync(path.join(SAMPLES, 'finance-metrics.xlsx'), buf)
  console.log('wrote finance-metrics.xlsx', buf.length, 'bytes')
}

// ---- PPTX: keep the real (rich) deck, but strip the images' alt text so the deck has
// an obvious "before" — un-alt'd charts on every slide. Remediation re-adds the alt. ----
async function buildPptx() {
  const file = path.join(SAMPLES, 'quarterly-town-hall.pptx')
  const z = await JSZip.loadAsync(fs.readFileSync(file))
  let stripped = 0
  for (const n of Object.keys(z.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    let s = await z.file(n).async('string')
    const before = s
    s = s.replace(/(<(?:p:cNvPr|pic:cNvPr)\b[^>]*?)\s+descr="[^"]*"/g, '$1') // drop alt text
    if (s !== before) stripped++
    z.file(n, s)
  }
  const buf = await z.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })
  fs.writeFileSync(file, buf)
  console.log('wrote quarterly-town-hall.pptx', buf.length, 'bytes (alt stripped from', stripped, 'slides)')
}

;(async () => { await buildDocx(); await buildXlsx(); await buildPptx(); console.log('done') })()
