// Approving alt text now WRITES it into the document, so what the reviewer saw and what the
// server applies must be the same thing. These pin the two places that could diverge.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { proposalsOf } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('the approve payload carries one value per image', () => {
  it('api.js sends approved_values alongside the single headline approved_value', () => {
    const src = read('api.js')
    expect(src).toMatch(/approved_values: opts\.approvedValues \?\? null/)
    expect(src).toMatch(/approved_value: approvedValue/)   // headline value still logged
  })

  it('EvidenceCard seeds one editor per proposal, from that image\'s own draft', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/useState\(\(\) => seedValues\(proposalList\)\)/)
    expect(src).toMatch(/const multi = proposalList\.length > 1/)
  })

  it('EvidenceCard sends the per-image values, and only on approval', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/status === 'approved' && proposalList\.length/)
    expect(src).toMatch(/approvedValues/)
  })

  it('every image is rendered beside its own textarea — never a value for an unseen image', () => {
    const src = read('ProposalEditors.jsx')
    expect(src).toMatch(/proposals\.map\(\(p, i\) =>/)
    expect(src).toMatch(/<ProposalThumb thumb=\{p\?\.thumb\}/)
    expect(src).toMatch(/onChange=\{\(e\) => onChange\(i, e\.target\.value\)\}/)
  })

  it('both review screens use the SAME editor, so the array index means the same proposal', () => {
    // approved_values[i] is proposal i on the server. Two divergent renderings could reorder
    // them and write a description onto the wrong image.
    for (const f of ['EvidenceCard.jsx', 'ReviewDrawer.jsx']) {
      expect(read(f)).toMatch(/from '\.\/ProposalEditors\.jsx'/)
      expect(read(f)).toMatch(/<ProposalEditors /)
    }
  })

  it('the Remediate drawer approves with the array, not just the first image', () => {
    const src = read('ReviewDrawer.jsx')
    expect(src).toMatch(/multi\s*\n?\s*\? onAct\(item\.id, 'approved', values\[0\], values\)/)
  })

  it('Remediate.act forwards approvedValues to the API', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/const act = \(id, kind, editedValue, approvedValues\)/)
    expect(src).toMatch(/\{ approvedValues: apiStatus === 'approved' \? \(approvedValues \|\| null\) : null \}/)
  })
})

describe('the inline card never blanket-approves images it did not show', () => {
  it('a multi-image row routes to the drawer instead of approving', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/const multiImage = \(item\.proposals\?\.length \|\| 0\) > 1/)
    expect(src).toMatch(/multiImage\s*\n?\s*\? <button className="qbtn approve"[^]*?onClick=\{onOpen\}/)
    expect(src).toMatch(/Review \{item\.proposals\.length\} images/)
  })

  it('a single-image row still approves inline', () => {
    expect(read('Remediate.jsx')).toMatch(/: <button className="qbtn approve" disabled=\{disabled\} onClick=\{onApprove\}>/)
  })
})

describe('proposalsOf — the list the editors are built from', () => {
  it('is empty for a judgement finding, so no editor and no write-back', () => {
    for (const empty of [null, {}, { proposals: null }, { proposals: [] }]) {
      expect(proposalsOf(empty)).toEqual([])
    }
  })

  it('preserves order, so values[i] lines up with the server\'s proposal i', () => {
    const item = { proposals: [{ locator: 'a' }, { locator: 'b' }, { locator: 'c' }] }
    expect(proposalsOf(item).map((p) => p.locator)).toEqual(['a', 'b', 'c'])
  })
})
