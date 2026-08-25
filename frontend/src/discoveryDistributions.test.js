import { describe, it, expect } from 'vitest'
import {
  ageBucketDistribution,
  sizeBucketDistribution,
  folderDistribution,
} from './discoveryDistributions.js'

// ── helpers ──────────────────────────────────────────────────────────────────

const yearsAgo = (y) => new Date(Date.now() - y * 365.25 * 24 * 3600 * 1000).toISOString()

const row = (overrides = {}) => ({
  file: 'test.pdf',
  source_modified: yearsAgo(2),
  size_kb: 500,
  parent_folder: '/Clinical/Policies',
  ...overrides,
})

// ── ageBucketDistribution ────────────────────────────────────────────────────

describe('ageBucketDistribution', () => {
  it('returns null for empty input', () => {
    expect(ageBucketDistribution([])).toBeNull()
    expect(ageBucketDistribution(null)).toBeNull()
  })

  it('returns null when no row has any date field', () => {
    const rows = [
      { file: 'a.pdf', source_modified: null, created_at: null },
      { file: 'b.pdf' },
    ]
    expect(ageBucketDistribution(rows)).toBeNull()
  })

  it('buckets a 6-month-old file into Under 1 year', () => {
    const rows = [row({ source_modified: yearsAgo(0.5) })]
    const d = ageBucketDistribution(rows)
    expect(d).not.toBeNull()
    const lt1 = d.buckets.find((b) => b.key === 'lt1')
    expect(lt1).toBeTruthy()
    expect(lt1.count).toBe(1)
  })

  it('buckets a 2-year-old file into 1–3 years', () => {
    const rows = [row({ source_modified: yearsAgo(2) })]
    const d = ageBucketDistribution(rows)
    const b = d.buckets.find((b) => b.key === '1to3')
    expect(b.count).toBe(1)
  })

  it('buckets a 4-year-old file into 3–5 years', () => {
    const rows = [row({ source_modified: yearsAgo(4) })]
    const d = ageBucketDistribution(rows)
    const b = d.buckets.find((b) => b.key === '3to5')
    expect(b.count).toBe(1)
  })

  it('buckets a 6-year-old file into Over 5 years', () => {
    const rows = [row({ source_modified: yearsAgo(6) })]
    const d = ageBucketDistribution(rows)
    const b = d.buckets.find((b) => b.key === 'gt5')
    expect(b.count).toBe(1)
  })

  it('falls back to created_at when source_modified is null', () => {
    const rows = [row({ source_modified: null, created_at: yearsAgo(0.3) })]
    const d = ageBucketDistribution(rows)
    const lt1 = d.buckets.find((b) => b.key === 'lt1')
    expect(lt1.count).toBe(1)
  })

  it('puts rows with no date into Unknown bucket', () => {
    const rows = [
      row({ source_modified: yearsAgo(1), created_at: null }),
      row({ source_modified: null, created_at: null }),
    ]
    const d = ageBucketDistribution(rows)
    const unk = d.buckets.find((b) => b.key === 'unknown')
    expect(unk).toBeTruthy()
    expect(unk.count).toBe(1)
  })

  it('balanced is true when sum equals total', () => {
    const rows = [row(), row({ source_modified: yearsAgo(4) })]
    const d = ageBucketDistribution(rows)
    expect(d.balanced).toBe(true)
    expect(d.sum).toBe(d.total)
  })

  it('drops empty buckets from the result', () => {
    const rows = [row({ source_modified: yearsAgo(6) })]
    const d = ageBucketDistribution(rows)
    // Should only contain the gt5 bucket; lt1, 1to3, 3to5 have count=0
    const keys = d.buckets.map((b) => b.key)
    expect(keys).not.toContain('lt1')
    expect(keys).toContain('gt5')
  })
})

// ── sizeBucketDistribution ───────────────────────────────────────────────────

describe('sizeBucketDistribution', () => {
  it('returns null for empty input', () => {
    expect(sizeBucketDistribution([])).toBeNull()
  })

  it('returns null when no row has size_kb', () => {
    const rows = [{ file: 'a.pdf', size_kb: null }, { file: 'b.pdf' }]
    expect(sizeBucketDistribution(rows)).toBeNull()
  })

  it('buckets a 50 KB file into Under 100 KB', () => {
    const d = sizeBucketDistribution([row({ size_kb: 50 })])
    expect(d.buckets.find((b) => b.key === 'tiny').count).toBe(1)
  })

  it('buckets a 500 KB file into 100 KB – 1 MB', () => {
    const d = sizeBucketDistribution([row({ size_kb: 500 })])
    expect(d.buckets.find((b) => b.key === 'small').count).toBe(1)
  })

  it('buckets a 5 MB file into 1 – 10 MB', () => {
    const d = sizeBucketDistribution([row({ size_kb: 5_000 })])
    expect(d.buckets.find((b) => b.key === 'medium').count).toBe(1)
  })

  it('buckets a 20 MB file into Over 10 MB', () => {
    const d = sizeBucketDistribution([row({ size_kb: 20_000 })])
    expect(d.buckets.find((b) => b.key === 'large').count).toBe(1)
  })

  it('accepts _sizeKb (inventoryOnlyRows field name)', () => {
    const d = sizeBucketDistribution([{ file: 'x.png', _sizeKb: 80 }])
    expect(d.buckets.find((b) => b.key === 'tiny').count).toBe(1)
  })

  it('routes null size_kb to unknown bucket', () => {
    const rows = [row({ size_kb: 500 }), row({ size_kb: null })]
    const d = sizeBucketDistribution(rows)
    const unk = d.buckets.find((b) => b.key === 'unknown')
    expect(unk.count).toBe(1)
  })

  it('balanced is true when sum equals total', () => {
    const rows = [row({ size_kb: 50 }), row({ size_kb: 500 }), row({ size_kb: null })]
    const d = sizeBucketDistribution(rows)
    expect(d.balanced).toBe(true)
    expect(d.sum).toBe(3)
  })
})

// ── folderDistribution ───────────────────────────────────────────────────────

describe('folderDistribution', () => {
  it('returns null for empty input', () => {
    expect(folderDistribution([])).toBeNull()
  })

  it('returns null when no row has a parent_folder', () => {
    const rows = [{ file: 'a.pdf', parent_folder: null }, { file: 'b.pdf' }]
    expect(folderDistribution(rows)).toBeNull()
  })

  it('counts files per folder', () => {
    const rows = [
      row({ parent_folder: '/Clinical' }),
      row({ parent_folder: '/Clinical' }),
      row({ parent_folder: '/HR' }),
    ]
    const d = folderDistribution(rows)
    expect(d.buckets.find((b) => b.key === '/Clinical').count).toBe(2)
    expect(d.buckets.find((b) => b.key === '/HR').count).toBe(1)
  })

  it('sorts buckets largest first', () => {
    const rows = [
      row({ parent_folder: '/HR' }),
      row({ parent_folder: '/Clinical' }),
      row({ parent_folder: '/Clinical' }),
    ]
    const d = folderDistribution(rows)
    expect(d.buckets[0].key).toBe('/Clinical')
  })

  it('collapses folders beyond topN into Other', () => {
    const rows = Array.from({ length: 12 }, (_, i) => row({ parent_folder: `/folder-${i}` }))
    const d = folderDistribution(rows, 10)
    const other = d.buckets.find((b) => b.key === '__other__')
    expect(other).toBeTruthy()
    expect(other.count).toBe(2)
  })

  it('routes null/missing parent_folder to root bucket', () => {
    const rows = [row({ parent_folder: '/HR' }), row({ parent_folder: null })]
    const d = folderDistribution(rows)
    const root = d.buckets.find((b) => b.key === '(root / no folder)')
    expect(root.count).toBe(1)
  })

  it('balanced is true', () => {
    const rows = [row({ parent_folder: '/A' }), row({ parent_folder: '/B' })]
    const d = folderDistribution(rows)
    expect(d.balanced).toBe(true)
    expect(d.sum).toBe(d.total)
  })
})
