import { describe, it, expect } from 'vitest'
import {
  assessablePct, isTruncated, compositionRows, statusRows, funnelStages, estateModel,
  statusFiles, ASSESSABLE_FORMATS,
} from './estateFunnel.js'

const INV = {
  discovered: 30000, assessment_eligible: 18692, truncated: false,
  by_format: { pdf: 8175, image: 7570, docx: 6223, xlsx: 2951, other: 2374, pptx: 1509, av: 1198 },
  by_status: { assessable: 18692, metadata_only: 8768, unsupported: 2374, excluded: 166 },
}

describe('estateFunnel model', () => {
  it('assessable% is eligible over discovered', () => {
    expect(Math.round(assessablePct(INV) * 100)).toBe(62)
    expect(assessablePct({ discovered: 0 })).toBe(0)      // no divide-by-zero
  })

  it('composition is largest-first and flags the assessable (green) formats', () => {
    const rows = compositionRows(INV)
    expect(rows[0].format).toBe('pdf')                    // biggest
    expect(rows.find((r) => r.format === 'image').assessable).toBe(false)
    expect(rows.find((r) => r.format === 'docx').assessable).toBe(true)
    expect(rows.every((r) => ASSESSABLE_FORMATS.includes(r.format) === r.assessable)).toBe(true)
  })

  it('status rows keep a stable order, assessable first', () => {
    expect(statusRows(INV).map((r) => r.status)).toEqual(['assessable', 'metadata_only', 'unsupported', 'excluded'])
  })

  it('the funnel is nine stages; 1-3 are real, 4-9 pending until scan data arrives', () => {
    const f = funnelStages(INV)
    expect(f).toHaveLength(9)
    expect(f[0].value).toBe(30000)                        // discovered
    expect(f[2].value).toBe(18692)                        // assessment eligible
    expect(f[3].value).toBeNull()                         // assessed — pending
    expect(f.every((s) => s.of === 30000)).toBe(true)     // every stage carries the denominator
  })

  it('scan/remediation progress fills the lower stages', () => {
    const f = funnelStages(INV, { assessed: 100, issues: 60, remediated: 30 })
    expect(f.find((s) => s.key === 'assessed').value).toBe(100)
    expect(f.find((s) => s.key === 'remediated').value).toBe(30)
  })

  it('truncation is surfaced so a capped estate is never shown as complete', () => {
    expect(isTruncated(INV)).toBe(false)
    expect(isTruncated({ discovered: 5, truncated: true })).toBe(true)
    expect(estateModel({ discovered: 5, truncated: true }).truncated).toBe(true)
  })

  it('statusFiles drills into a bucket and is honest when the sample is capped', () => {
    const inv = {
      by_status: { unsupported: 2374, excluded: 1 },
      samples: {
        unsupported: [{ id: 'a', name: 'notes.txt', format: 'other' }, { id: 'b', name: 'clip.mp3', format: 'av' }],
        excluded: [{ id: 'z', name: 'remediated_report.pdf', format: 'pdf' }],
      },
    }
    const big = statusFiles(inv, 'unsupported')
    expect(big.total).toBe(2374)          // the TRUE bucket size, not the sample
    expect(big.shown).toBe(2)
    expect(big.capped).toBe(true)         // 2 shown of 2374 — say so
    expect(big.files[0]).toMatchObject({ name: 'notes.txt', format: 'other', label: 'Other' })

    const small = statusFiles(inv, 'excluded')
    expect(small.capped).toBe(false)      // whole bucket fits in the sample
    expect(small.shown).toBe(1)

    const empty = statusFiles(inv, 'assessable')   // no samples/total for this status
    expect(empty).toMatchObject({ files: [], shown: 0, total: 0, capped: false })
  })
})
