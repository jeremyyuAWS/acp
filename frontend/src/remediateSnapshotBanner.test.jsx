import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Remediate.jsx'), 'utf8').replace(/\{\/\*[\s\S]*?\*\/\}/g, '')

describe('Remediate snapshot separation', () => {
  it('recognizes every finished assessment state', () => {
    for (const state of ['done', 'complete', 'completed', 'finalized', 'cancelled', 'interrupted', 'superseded']) expect(src).toContain(`'${state}'`)
    expect(src).toMatch(/assessRunning\s*=\s*run\?\.status.*_DONE_STATES/)
  })

  it('labels prior results only when assessment is running and results exist', () => {
    expect(src).toMatch(/showPriorResultsNotice\s*=\s*assessRunning.*files\.length/)
    expect(src).toMatch(/\{showPriorResultsNotice &&/)
    expect(src).toContain('Previous remediation results · read only')
    expect(src).toMatch(/assessedAt.*previous assessment/s)
  })

  it('does not compete with the App-owned assessment progress card', () => {
    const start = src.indexOf('showPriorResultsNotice &&')
    const block = src.slice(start, src.indexOf('RemediationRunHeader', start))
    expect(block).not.toContain('A new assessment is running')
    expect(block).not.toContain('View assessment progress')
    expect(block).not.toContain('Continue from previous results')
    expect(block).toContain('role="status"')
  })
})
