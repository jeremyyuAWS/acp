import { describe, it, expect } from 'vitest'
import fs from 'fs'
import JSZip from 'jszip'
import { transformXlsx, transformPptx, transformSheetXml, transformSlideXml } from './exportDeliverables.js'

const wellFormed = (xml) => {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  return !doc.querySelector('parsererror')
}
const load = (p) => JSZip.loadAsync(fs.readFileSync(p))
const roundTrip = async (zip) => JSZip.loadAsync(await zip.generateAsync({ type: 'nodebuffer' }))

describe('export deliverables — Status column injection', () => {
  it('Excel: adds a Status column to the Coverage Matrix, preserving every row', async () => {
    const zip = await transformXlsx(await load('public/exports/coverage-matrix.xlsx'))
    const out = await roundTrip(zip) // ensure the zip is still valid after editing
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

  it('PowerPoint: adds a Status column to every table slide (skips tableless slides)', async () => {
    const zip = await transformPptx(await load('public/exports/method-deck.pptx'))
    const out = await roundTrip(zip)
    let tableSlides = 0
    let row145 = null
    for (const path of Object.keys(out.files).filter((n) => /slide\d+\.xml$/.test(n))) {
      const xml = await out.file(path).async('string')
      expect(wellFormed(xml)).toBe(true)
      if (!/<a:tbl>/.test(xml)) continue // title / no-table slide — left untouched
      tableSlides++
      const grid = xml.match(/<a:tblGrid>[\s\S]*?<\/a:tblGrid>/)[0]
      expect((grid.match(/<a:gridCol /g) || []).length).toBe(6) // 5 + status
      expect(xml).toMatch(/<a:t>Status<\/a:t>/) // header cell
      const r = (xml.match(/<a:tr[ >][\s\S]*?<\/a:tr>/g) || []).find((rr) => /<a:t>1\.4\.5[^<]*<\/a:t>/.test(rr))
      if (r) row145 = r
    }
    expect(tableSlides).toBeGreaterThan(0)
    // the 1.4.5 row (wherever it lives) shows the OCR status
    expect(row145).toMatch(/<a:t>Live · AI OCR<\/a:t>/)
  })

  it('table width stays constant (no overflow) and section rows still span full width', async () => {
    const zip = await load('public/exports/method-deck.pptx')
    const slidePath = Object.keys(zip.files).filter((n) => /slide\d+\.xml$/.test(n)).sort()
    let s1
    for (const p of slidePath) { const xml = await zip.file(p).async('string'); if (/<a:tbl>/.test(xml)) { s1 = xml; break } }
    const sum = (xml) => [...xml.match(/<a:tblGrid>[\s\S]*?<\/a:tblGrid>/)[0].matchAll(/<a:gridCol w="(\d+)">/g)].reduce((a, m) => a + +m[1], 0)
    const after = transformSlideXml(s1)
    expect(Math.abs(sum(after) - sum(s1))).toBeLessThan(10) // same total width (rounding only)
    expect(after).toMatch(/gridSpan="6"/) // section header span widened 5 -> 6
  })
})
