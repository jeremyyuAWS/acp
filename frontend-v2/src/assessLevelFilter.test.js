import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { WCAG } from './wcagCatalog.js'
import { allRules } from './rules/index.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Reconstruct AssessRunner's level resolution from the same sources it uses, so this test
// guards the actual runtime behaviour (levelOf is module-local, not exported).
const SC_LEVEL = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta.level]))
const CATALOG_LEVEL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))
const scOf = (w) => ((String(w || '')).replace(/^SC_/, '').replace(/_/g, '.').match(/\d+\.\d+\.\d+/) || [])[0]
const levelOf = (x) => x.level || SC_LEVEL[scOf(x.wcag)] || CATALOG_LEVEL[scOf(x.wcag)] || 'A'
const RANK = { A: 1, AA: 2, AAA: 3 }
const blocksAt = (x, target) => RANK[levelOf(x)] <= RANK[target]

describe('Assess level filter resolves detector-only criteria to their true WCAG level', () => {
  it('1.4.9 (Images of Text, No Exception) is AAA and does NOT block at an AA target', () => {
    // The exact finding api/ocr.py emits — no `level` field, and no rule module declares 1.4.9.
    const f = { ruleId: 'OCR_IMAGE_OF_TEXT_STRICT', wcag: '1.4.9 Images of Text (No Exception)', severity: 'MODERATE' }
    expect(levelOf(f)).toBe('AAA')
    expect(blocksAt(f, 'AA')).toBe(false) // the reported bug: it used to block at AA
    expect(blocksAt(f, 'A')).toBe(false)
    expect(blocksAt(f, 'AAA')).toBe(true)
  })

  it('every AAA criterion ACP can detect resolves to AAA, so none leak into an AA scope', () => {
    // Detector-only AAA criteria that have no remediator rule module (the systemic form of the bug).
    for (const sc of ['1.4.6', '2.4.9', '1.4.8', '2.4.10', '3.1.5']) {
      const f = { wcag: 'SC_' + sc.replace(/\./g, '_') }
      expect(levelOf(f), sc).toBe('AAA')
      expect(blocksAt(f, 'AA'), sc).toBe(false)
    }
  })

  it('A/AA criteria still block at their target (the fix does not over-correct)', () => {
    expect(blocksAt({ wcag: 'SC_1_1_1' }, 'AA')).toBe(true) // A blocks at AA
    expect(blocksAt({ wcag: 'SC_1_4_3' }, 'AA')).toBe(true) // AA blocks at AA
    expect(blocksAt({ wcag: 'SC_1_4_3' }, 'A')).toBe(false) // AA does not block at A
  })

  it('an explicit level field (SIM findings) still wins over the catalog', () => {
    expect(levelOf({ wcag: 'SC_1_4_9', level: 'A' })).toBe('A')
  })

  it('AssessRunner wires the WCAG catalog as the level fallback', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/import \{ WCAG \} from '\.\/wcagCatalog\.js'/)
    expect(s).toMatch(/CATALOG_LEVEL = Object\.fromEntries\(WCAG\.map/)
    expect(s).toMatch(/SC_LEVEL\[scOf\(x\.wcag\)\] \|\| CATALOG_LEVEL\[scOf\(x\.wcag\)\] \|\| 'A'/)
  })
})
