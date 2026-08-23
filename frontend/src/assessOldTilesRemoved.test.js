// assessOldTilesRemoved.test.js
// Asserts that the old post-run "Needs attention" verdict block and four KPI tiles
// (including the est. hours effort tile) have been removed from AssessRunner.jsx.
// AssessRunner.jsx is KEPT ON DISK and still runs the assessment; only the inline
// result-summary block is gone — replaced by AssessSummary, which App.jsx mounts below it.
// If this test fails, the old block was re-added — remove it again.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(HERE, 'AssessRunner.jsx'), 'utf8')

describe('old post-run summary block is removed from AssessRunner', () => {
  it('no longer renders the "Needs attention" verdict headline', () => {
    expect(src).not.toContain('Needs attention — what to fix')
    expect(src).not.toContain('Ready to certify')
  })

  it('no longer renders the effort estimate tile', () => {
    expect(src).not.toContain('human effort')
    expect(src).not.toContain('fmtEffort')
    expect(src).not.toContain('estimateEffortMin')
    expect(src).not.toContain('EFFORT_BASIS')
  })

  it('no longer imports from effort.js', () => {
    expect(src).not.toMatch(/from\s+['"]\.\/effort\.js['"]/)
  })

  it('no longer renders the four-tile KPI grid', () => {
    expect(src).not.toContain('assesstiles')
    expect(src).not.toContain('atile')
  })

  it('still exists on disk as AssessRunner (the runner itself is kept)', () => {
    expect(src.length).toBeGreaterThan(1000)
    expect(src).toContain('export default function AssessRunner')
  })
})
