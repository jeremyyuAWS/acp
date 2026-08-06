import { describe, it, expect } from 'vitest'
import fs from 'fs'
import JSZip from 'jszip'
import { transformXlsx, transformPptx, transformSheetXml, transformSlideXml } from './exportDeliverables.js'

const wellFormed = (xml) => {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  return !doc.querySelector('parsererror')
}
const load = (p) => JSZip.loadAsync(fs.readFileSync(p))

// Minimal slide XML: 5-column table, a section header row (gridSpan=5), and a 1.4.5 data row.
// Used instead of loading method-deck.pptx so the test doesn't depend on a binary fixture.
const SLIDE_WITH_TABLE = [
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
  '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"',
  '       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"',
  '       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">',
  '  <p:cSld><p:spTree>',
  '    <p:graphicFrame>',
  '      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">',
  '        <a:tbl>',
  '          <a:tblPr/>',
  '          <a:tblGrid>',
  '            <a:gridCol w="1000000"/>',
  '            <a:gridCol w="1000000"/>',
  '            <a:gridCol w="1000000"/>',
  '            <a:gridCol w="1000000"/>',
  '            <a:gridCol w="1000000"/>',
  '          </a:tblGrid>',
  '          <a:tr h="370840">',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>SC</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>Criterion</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>Level</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>Source</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>Phase</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '          </a:tr>',
  '          <a:tr h="370840">',
  '            <a:tc gridSpan="5"><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>Principle 1</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc hMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc hMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc hMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc hMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>',
  '          </a:tr>',
  '          <a:tr h="370840">',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr/><a:t>1.4.5</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr/><a:t>Images of Text</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr/><a:t>AA</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr/><a:t>Shipped</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '            <a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr/><a:t>Phase 1</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>',
  '          </a:tr>',
  '        </a:tbl>',
  '      </a:graphicData></a:graphic>',
  '    </p:graphicFrame>',
  '  </p:spTree></p:cSld>',
  '</p:sld>',
].join('\n')

const sum = (xml) => [...xml.match(/<a:tblGrid>[\s\S]*?<\/a:tblGrid>/)[0].matchAll(/<a:gridCol w="(\d+)">/g)].reduce((a, m) => a + +m[1], 0)

describe('export deliverables — Status column injection', () => {
  it('Excel: adds a Status column to the Coverage Matrix, preserving every row', async () => {
    const zip = await transformXlsx(await load('public/exports/coverage-matrix.xlsx'))
    const out = await JSZip.loadAsync(await zip.generateAsync({ type: 'nodebuffer' }))
    const xml = await out.file('xl/worksheets/sheet2.xml').async('string')
    expect(wellFormed(xml)).toBe(true)
    expect(xml).toMatch(/<dimension ref="A1:P\d+"\/>/) // range widened O -> P
    expect(xml).toMatch(/<c r="P1"[^>]*><is><t>Status<\/t>/) // header label
    // every data row got a P cell
    const dataRows = (xml.match(/<row r="(\d+)"/g) || []).length
    const pCells = (xml.match(/<c r="P\d+"/g) || []).length
    expect(pCells).toBe(dataRows)
    // a known criterion carries the real platform status
    const row145 = xml.match(/<row r="\d+"[^>]*>(?:(?!<\/row>)[\s\S])*?<t>1\.4\.5<\/t>[\s\S]*?<\/row>/)
    expect(row145).toBeTruthy()
    expect(row145[0]).toMatch(/<c r="P\d+"[^>]*><is><t>Live · AI OCR<\/t>/)
  })

  it('PowerPoint: adds a Status column to a table slide', () => {
    const after = transformSlideXml(SLIDE_WITH_TABLE)
    expect(wellFormed(after)).toBe(true)
    const grid = after.match(/<a:tblGrid>[\s\S]*?<\/a:tblGrid>/)[0]
    expect((grid.match(/<a:gridCol /g) || []).length).toBe(6) // 5 original + Status
    expect(after).toMatch(/<a:t>Status<\/a:t>/) // header cell injected
    // 1.4.5 row gets the correct status value
    const row = (after.match(/<a:tr[ >][\s\S]*?<\/a:tr>/g) || []).find((r) => /<a:t>1\.4\.5<\/a:t>/.test(r))
    expect(row).toBeTruthy()
    expect(row).toMatch(/<a:t>Live · AI OCR<\/a:t>/)
  })

  it('table width stays constant and section rows widen span', () => {
    const after = transformSlideXml(SLIDE_WITH_TABLE)
    expect(Math.abs(sum(after) - sum(SLIDE_WITH_TABLE))).toBeLessThan(10) // same total width
    expect(after).toMatch(/gridSpan="6"/) // section header span widened 5 -> 6
  })

  it('transformSlideXml is a no-op on slides without tables', () => {
    const noTable = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree/></p:cSld></p:sld>'
    expect(transformSlideXml(noTable)).toBe(noTable)
  })
})
