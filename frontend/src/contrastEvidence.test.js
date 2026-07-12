import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { parseContrast } from './contrastEvidence.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('parseContrast — real colours + ratio from the finding detail', () => {
  it('parses the producer format', () => {
    const c = parseContrast('Text #A0A0A0 on #FFFFFF is 2.6:1 (needs 4.5:1)')
    expect(c).toEqual({ fg: '#A0A0A0', bg: '#FFFFFF', ratio: 2.6, needs: 4.5, passes: false })
  })

  it('marks a passing pair (evidence stays honest either way)', () => {
    expect(parseContrast('Text #333333 on #FFFFFF is 12.6:1 (needs 4.5:1)').passes).toBe(true)
  })

  it('returns null when the detail has no colours (html/pdf heuristics)', () => {
    expect(parseContrast('Inline colour likely below 4.5:1')).toBeNull()
    expect(parseContrast('')).toBeNull()
    expect(parseContrast(undefined)).toBeNull()
  })

  it('never invents numbers — a malformed ratio is rejected, not defaulted', () => {
    expect(parseContrast('Text #111111 on #222222 is :1 (needs 4.5:1)')).toBeNull()
  })
})

describe('the swatch is wired as visual evidence in the card', () => {
  it('buildEvidenceCard carries the raw detail', () => {
    expect(read('reviewCard.js')).toMatch(/detail: item\?\.detail \|\| ''/)
  })
  it('EvidenceCard renders the unified BeforeAfterEvidence (contrast routes through it)', () => {
    const s = read('EvidenceCard.jsx')
    expect(s).toMatch(/<BeforeAfterEvidence card=\{card\} \/>/)
    expect(read('BeforeAfterEvidence.jsx')).toMatch(/ContrastSwatch/)
  })
})
