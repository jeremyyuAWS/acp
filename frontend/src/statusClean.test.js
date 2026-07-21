import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { statusOf, STATUS_BADGE } from './FileDrawer.jsx'

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'FileDrawer.jsx'), 'utf8')

describe('FileDrawer renders a clean file honestly (no self-contradiction)', () => {
  it('journey marks Remediate not-needed (skip), never in-progress, for a clean file', () => {
    expect(src).toMatch(/if \(st === 'clean'\) return \[\.\.\.base, 'skip'/)
  })
  it('score line shows "no findings" instead of a bare n/a for a clean file', () => {
    expect(src).toMatch(/st === 'clean' && file\.score === null/)
    expect(src).toMatch(/no findings/)
  })
  it('suppresses the auto-remediate recommendation card when there are no findings', () => {
    expect(src).toMatch(/file\.rec && issues\.length > 0 && \(\(\) =>/)
  })
})

// A file's verdict must key 'issues' on ACTUAL findings — not merely on `compliant` being
// false. A not-certifiable file with zero findings (an unscored discover/skip record) is
// 'clean', so it never lands on the "open findings / Remediate in progress" path.
describe('statusOf — clean vs issues', () => {
  it('classifies a not-certifiable, zero-finding file as clean (not issues)', () => {
    expect(statusOf({ status: 'discovered', compliant: 0, issues: [], score: null })).toBe('clean')
    expect(statusOf({ status: 'skipped', compliant: 0, issues: [] })).toBe('clean')
    expect(statusOf({ status: 'analysed', compliant: 0, issues: [] })).toBe('clean')
    expect(statusOf({ status: 'analysed', compliant: 0 })).toBe('clean') // undefined issues → clean
  })

  it('classifies a file WITH findings as issues', () => {
    expect(statusOf({ status: 'analysed', compliant: 0, issues: [{ wcag: '1.1.1' }] })).toBe('issues')
  })

  it('keeps the existing verdicts intact', () => {
    expect(statusOf({ status: 'analysed', compliant: 1, issues: [] })).toBe('certifiable')
    expect(statusOf({ status: 'analysed', compliant: 1, issues: [{ wcag: '1.1.1' }] })).toBe('certifiable')
    expect(statusOf({ status: 'error', compliant: 0, issues: [] })).toBe('unanalysable')
    expect(statusOf({ status: 'uncertain', compliant: 0, issues: [] })).toBe('uncertain')
  })

  it('has a badge colour so list views and the drawer never crash on clean', () => {
    expect(STATUS_BADGE.clean).toBeTruthy()
    expect(STATUS_BADGE.clean).toHaveLength(2)
  })
})
