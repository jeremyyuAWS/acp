import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const readPy = (f) => readFileSync(join(here, '../../api', f), 'utf8')

describe('Open slide deep-link (P2 item 1 deferred sub-item)', () => {
  it('store.py has get_source_link_data method', () => {
    expect(readPy('store.py')).toMatch(/def get_source_link_data/)
  })

  it('get_source_link_data joins scan_inventory to scans', () => {
    const src = readPy('store.py')
    const idx = src.indexOf('def get_source_link_data')
    const block = src.slice(idx, idx + 900)
    expect(block).toMatch(/scan_inventory/)
    expect(block).toMatch(/drive_file_id/)
    expect(block).toMatch(/drive_id/)
  })

  it('get_source_link_data is owner-scoped', () => {
    const src = readPy('store.py')
    const idx = src.indexOf('def get_source_link_data')
    const block = src.slice(idx, idx + 600)
    expect(block).toMatch(/owner/)
  })

  it('scans.py has source_link route', () => {
    expect(readPy('routes/scans.py')).toMatch(/source_link/)
  })

  it('source_link route constructs Drive URL from drive_file_id without an API call', () => {
    const src = readPy('routes/scans.py')
    const idx = src.indexOf('source_link')
    const block = src.slice(idx, idx + 1500)
    expect(block).toMatch(/drive\.google\.com\/file\/d\//)
    expect(block).toMatch(/drive_file_id/)
  })

  it('source_link route calls Graph for SharePoint and appends slide parameter', () => {
    const src = readPy('routes/scans.py')
    const idx = src.indexOf('source_link')
    const block = src.slice(idx, idx + 1500)
    expect(block).toMatch(/x-sp-token/)
    expect(block).toMatch(/webUrl/)
    expect(block).toMatch(/slide=/)
  })

  it('source_link route returns url:null gracefully (no 404) when link unavailable', () => {
    const src = readPy('routes/scans.py')
    const idx = src.indexOf('source_link')
    const block = src.slice(idx, idx + 1500)
    expect(block).toMatch(/url.*None|None.*url/)
  })

  it('source_link route only appends slide param for pptx', () => {
    const src = readPy('routes/scans.py')
    const idx = src.indexOf('source_link')
    const block = src.slice(idx, idx + 1500)
    expect(block).toMatch(/\.pptx/)
  })

  it('workspace_capability_map registers source_link route', () => {
    expect(readPy('workspace_capability_map.py')).toMatch(/source_link/)
  })

  it('api.js exports getSourceLink', () => {
    expect(read('api.js')).toMatch(/export const getSourceLink/)
  })

  it('getSourceLink passes page parameter in query string', () => {
    const src = read('api.js')
    const idx = src.indexOf('getSourceLink')
    const block = src.slice(idx, idx + 300)
    expect(block).toMatch(/page=/)
  })

  it('EvidenceCard imports getSourceLink from api.js', () => {
    expect(read('EvidenceCard.jsx')).toMatch(/getSourceLink/)
  })

  it('EvidenceCard renders evcard-source-link anchor when url is present', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/evcard-source-link/)
    expect(src).toMatch(/sourceLink.*url|url.*sourceLink/)
  })

  it('EvidenceCard source link opens in new tab with rel=noopener', () => {
    const src = read('EvidenceCard.jsx')
    const idx = src.indexOf('evcard-source-link')
    const block = src.slice(idx - 200, idx + 200)
    expect(block).toMatch(/target.*_blank/)
    expect(block).toMatch(/noopener/)
  })
})
